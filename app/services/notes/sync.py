"""
Finds the lessons and files of the student's courses in UniLearn (or any Moodle) and keeps one LessonNote per lesson.

Uses the standard web services core_enrol_get_users_courses and core_course_get_contents.
Nothing is processed here: the student starts each lesson with "Make notes" (worker.py).
A lesson whose files changed keeps its notes and shows "New material".
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import LessonNote, NoteSource, User, UserRole
from app.services import unilearn_client
from app.services.my_courses import student_course_codes
from app.services.notes.extract import kind_of

logger = logging.getLogger(__name__)
BUSY = {"waiting", "syncing", "transcribing", "processing"}


def _file_key(f: Dict[str, Any]) -> str:
    """Moodle's contenthash when the site sends it; otherwise name + size + date (enough to see a change)."""
    return f.get("contenthash") or hashlib.sha1(f"{f.get('filename')}|{f.get('filesize')}|{f.get('timemodified')}".encode()).hexdigest()


def sync_materials(db: Session, user: User) -> Dict[str, Any]:
    info = unilearn_client.call(db, user, "core_webservice_get_site_info")
    courses = unilearn_client.call(db, user, "core_enrol_get_users_courses", userid=info["userid"])
    codes = None if user.role == UserRole.PROFESSOR else student_course_codes(db, user)
    mine = {(n.course_code, n.section_ext_id): n for n in db.scalars(select(LessonNote).where(LessonNote.user_id == user.id))}
    seen, queued, files_total = set(), [], 0
    for c in courses:
        code = str(c.get("shortname", "")).upper()
        if codes is not None and code not in codes:
            continue
        contents = unilearn_client.call(db, user, "core_course_get_contents", courseid=c["id"])
        for sec in contents:
            files = []
            for m in sec.get("modules", []):
                for f in m.get("contents", []) or []:
                    kind = kind_of(f.get("filename", ""), f.get("mimetype", ""))
                    if f.get("type") == "file" and kind and f.get("fileurl"):
                        files.append((m, f, kind))
            if not files:
                continue
            files_total += len(files)
            key = (code, int(sec["id"]))
            note = mine.get(key)
            if note is None:
                note = LessonNote(user_id=user.id, course_code=code, section_ext_id=int(sec["id"]), course_name=c.get("fullname") or code,
                                  lesson_name=sec.get("name") or "Lesson", status="new", updated_at=datetime.now())
                db.add(note)
                db.flush()
                mine[key] = note
            note.course_name = c.get("fullname") or code
            note.lesson_name = sec.get("name") or note.lesson_name
            note.position = int(sec.get("section") or 0)
            have = {s.resource_ext_id: s for s in note.sources}
            wanted = set()
            for m, f, kind in files:
                rid = int(m["id"])
                wanted.add(rid)
                src = have.get(rid)
                if src is None:
                    src = NoteSource(resource_ext_id=rid)
                    note.sources.append(src)
                src.filename, src.kind, src.fileurl = f["filename"], kind, f["fileurl"]
                src.contenthash, src.filesize = _file_key(f), int(f.get("filesize") or 0)
            for rid, src in have.items():
                if rid not in wanted:
                    note.sources.remove(src)
            note.sources_hash = hashlib.sha1("".join(sorted(s.contenthash for s in note.sources)).encode()).hexdigest()
            # nothing starts on its own: the student presses "Make notes" (or "Make notes again" when files changed)
            seen.add(note.id)
    for note in mine.values():   # lessons or files removed by the lecturer; notes the student edited stay
        if note.id not in seen and not note.edited and note.status not in BUSY - {"waiting"}:
            db.delete(note)
    db.commit()
    new = sum(1 for n in mine.values() if n.id in seen and n.status == "new")
    logger.info("Smart Notes sync for %s: %d lesson(s), %d file(s), %d not made yet", user.email, len(seen), files_total, new)
    return {"lessons": len(seen), "files": files_total, "queued": 0, "not_made": new}


def busy_note_ids(db: Session) -> List[int]:
    return list(db.scalars(select(LessonNote.id).where(LessonNote.status.in_(BUSY))))
