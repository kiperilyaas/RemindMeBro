"""
"Find exam dates" (Free plan): the job of one student, started with the button and run in a background thread.

Lists the files of the courses the student follows in UniLearn (core_course_get_contents, like Smart Notes but with
no notes), downloads and reads the new ones (text cache shared with Smart Notes), and searches each file once for
everybody (FileScan by content hash). Audio and video are not read: no transcription on the Free plan.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.database.db import SessionLocal
from app.database.models import ExtractedText, FileScan, FoundExamDate, User, UserRole
from app.services import unilearn_client
from app.services.exam_dates import finder
from app.services.my_courses import student_course_codes
from app.services.notes.extract import ExtractError, extract_text, kind_of

logger = logging.getLogger(__name__)
READABLE = {"pdf", "slides", "document", "text"}

_lock = threading.Lock()
_jobs: Dict[int, Dict[str, Any]] = {}


def status(user_id: int) -> Dict[str, Any]:
    with _lock:
        return dict(_jobs.get(user_id) or {"state": "idle"})


def _update(user_id: int, **kw: Any) -> None:
    with _lock:
        _jobs.setdefault(user_id, {}).update(kw)


def start(user_id: int) -> Dict[str, Any]:
    """Starts the search for this student (one at a time per student). Returns the status."""
    with _lock:
        job = _jobs.get(user_id)
        if job and job.get("state") == "running":
            return dict(job)
        _jobs[user_id] = {"state": "running", "files_total": 0, "files_done": 0, "current": None, "found": 0,
                          "warnings": [], "started_at": datetime.now().isoformat(timespec="seconds")}
    threading.Thread(target=_run, args=(user_id,), name=f"exam-dates-{user_id}", daemon=True).start()
    return status(user_id)


def _files(db, user: User) -> List[Dict[str, Any]]:
    from app.services.notes.sync import _file_key
    info = unilearn_client.call(db, user, "core_webservice_get_site_info")
    courses = unilearn_client.call(db, user, "core_enrol_get_users_courses", userid=info["userid"])
    codes = None if user.role == UserRole.PROFESSOR else student_course_codes(db, user)
    out = []
    for c in courses:
        code = str(c.get("shortname", "")).upper()
        if codes is not None and code not in codes:
            continue
        for sec in unilearn_client.call(db, user, "core_course_get_contents", courseid=c["id"]):
            for m in sec.get("modules", []):
                for f in m.get("contents", []) or []:
                    kind = kind_of(f.get("filename", ""), f.get("mimetype", ""))
                    if f.get("type") == "file" and kind in READABLE and f.get("fileurl"):
                        out.append({"course_code": code, "course_name": c.get("fullname") or code, "filename": f["filename"],
                                    "kind": kind, "fileurl": f["fileurl"], "contenthash": _file_key(f)})
    return out


def _ask(messages: List[Dict[str, str]], fast: bool) -> str:
    from app.services import llm_extractor
    return llm_extractor._chat(messages, json_mode=True, temperature=0.0, fast=fast)


def scan_file(db, user: User, f: Dict[str, Any]) -> int:
    """Reads and searches one file (if not done yet with this finder version). Returns how many dates it has."""
    from app.services import llm_extractor
    from app.services.notes.worker import _download
    done = db.get(FileScan, f["contenthash"])
    if done is not None and done.version == finder.VERSION and not done.error:
        return done.found
    cached = db.get(ExtractedText, f["contenthash"])
    if cached is None:
        path = _download(db, user, SimpleNamespace(contenthash=f["contenthash"], filename=f["filename"], fileurl=f["fileurl"]))
        cached = ExtractedText(contenthash=f["contenthash"], kind=f["kind"], text=extract_text(path, f["kind"]))
        db.add(cached)
        db.commit()
    model = settings.AI_MODEL if settings.ai_remote else settings.OLLAMA_MODEL
    found, thrown, calls = finder.find_in_file(cached.text, f["filename"], f["course_name"], settings.reference_now().date(),
                                               _ask, llm_extractor.parse_llm_json, double_check=settings.EXAM_DATES_DOUBLE_CHECK)
    for x in found:
        row = FoundExamDate(contenthash=f["contenthash"], course_code=f["course_code"], filename=f["filename"], page=x.page,
                            kind=x.kind, title=x.title, on_date=datetime.combine(x.on_date, datetime.min.time()),
                            at_time=x.at_time, room=x.room, quote=x.quote, year_written=x.year_written, model=model)
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:
            pass
    if done is None:
        done = FileScan(contenthash=f["contenthash"])
        db.add(done)
    done.version, done.filename, done.course_code = finder.VERSION, f["filename"], f["course_code"]
    done.found, done.rejected, done.error, done.scanned_at = len(found), thrown, None, datetime.now()
    db.commit()
    logger.info("Exam dates: %s (%s): %d found, %d thrown away, %d AI call(s)", f["filename"], f["course_code"], len(found), thrown, calls)
    return len(found)


def _run(user_id: int) -> None:
    from app.services.llm_extractor import LLMUnavailableError
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        conn = unilearn_client.get_connection(db, user) if user else None
        if conn is None or conn.status != "connected":
            _update(user_id, state="error", error="Connect UniLearn first: the course files come from there.")
            return
        files = _files(db, user)
        _update(user_id, files_total=len(files))
        warnings: List[str] = []
        for i, f in enumerate(files, 1):
            _update(user_id, current=f["filename"], files_done=i - 1)
            try:
                scan_file(db, user, f)
            except (ExtractError, LLMUnavailableError) as exc:
                db.rollback()
                warnings.append(f"{f['filename']}: {exc}")
                logger.warning("Exam dates: %s skipped: %s", f["filename"], exc)
        _update(user_id, files_done=len(files), current=None, warnings=warnings[:5])
        _update(user_id, state="done", finished_at=datetime.now().isoformat(timespec="seconds"),
                error=("The AI could not read some files. Try again later." if warnings and len(warnings) == len(files) else None))
    except unilearn_client.UniLearnError as exc:
        db.rollback()
        _update(user_id, state="error", error=f"UniLearn: {exc}")
    except Exception as exc:
        db.rollback()
        logger.exception("Exam dates: search failed for user %s", user_id)
        _update(user_id, state="error", error=f"Unexpected error: {exc.__class__.__name__}")
    finally:
        db.close()
