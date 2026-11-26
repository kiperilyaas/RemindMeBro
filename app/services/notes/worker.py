"""
Background queue for Smart Notes: one thread, one lesson at a time (Whisper and llama3.2 already use every CPU core).

Steps and the status the app shows: syncing (download + read files) -> transcribing (recordings)
-> processing (the AI writes the notes) -> ready, or error with a message.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, Set

import httpx

from app.config import settings
from app.database.db import SessionLocal
from app.database.models import ExtractedText, LessonNote, NoteSource, User
from app.services import unilearn_client
from app.services.llm_extractor import LLMUnavailableError
from app.services.notes.extract import MEDIA_KINDS, ExtractError, extract_text
from app.services.notes.generator import NotesError, generate, to_markdown
from app.services.notes.transcribe import TranscribeError, transcribe

logger = logging.getLogger(__name__)
_q: "queue.Queue[int]" = queue.Queue()
_pending: Set[int] = set()
_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def enqueue(note_id: int) -> None:
    global _thread
    with _lock:
        if note_id in _pending:
            return
        _pending.add(note_id)
        _q.put(note_id)
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run, name="smart-notes", daemon=True)
            _thread.start()


def is_queued(note_id: int) -> bool:
    with _lock:
        return note_id in _pending


def _run() -> None:
    while True:
        note_id = _q.get()
        try:
            process(note_id)
        except Exception:   # never kill the thread
            logger.exception("Smart Notes: lesson %s failed", note_id)
        finally:
            with _lock:
                _pending.discard(note_id)


def _download(db, user: User, src: NoteSource) -> Path:
    folder = Path(settings.MATERIALS_DIR) / src.contenthash[:2]
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{src.contenthash}{Path(src.filename).suffix.lower()}"
    if target.is_file():
        return target
    conn = unilearn_client.get_connection(db, user)
    if conn is None or conn.status != "connected":
        raise ExtractError("UniLearn is not connected. Connect it from the Connect page.")
    token = unilearn_client.decrypt(conn.access_token_enc)
    tmp = target.with_suffix(target.suffix + ".part")
    try:
        with httpx.stream("GET", src.fileurl, params={"token": token}, timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as r:
            if r.status_code != 200:
                raise ExtractError(f"Could not download {src.filename} (HTTP {r.status_code}).")
            if "application/json" in r.headers.get("content-type", ""):
                r.read()
                raise ExtractError(f"Could not download {src.filename}: {r.json().get('error', 'access denied')}")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_bytes(1024 * 1024):
                    fh.write(chunk)
    except httpx.HTTPError as exc:
        raise ExtractError(f"UniLearn is not reachable ({exc.__class__.__name__}).") from exc
    tmp.replace(target)
    return target


def _set(db, note: LessonNote, status: str) -> None:
    note.status, note.updated_at = status, datetime.now()
    db.commit()


def process(note_id: int) -> None:
    db = SessionLocal()
    try:
        note = db.get(LessonNote, note_id)
        if note is None:
            return
        user = db.get(User, note.user_id)
        target_hash = note.sources_hash
        try:
            _set(db, note, "syncing")
            texts, warnings = [], []
            for src in list(note.sources):
                cached = db.get(ExtractedText, src.contenthash)
                if cached is None:
                    try:
                        path = _download(db, user, src)
                        if src.kind in MEDIA_KINDS:
                            _set(db, note, "transcribing")
                            text, lang = transcribe(path)
                        else:
                            text, lang = extract_text(path, src.kind), None
                    except (ExtractError, TranscribeError) as exc:
                        warnings.append(str(exc))   # one unreadable file does not stop the lesson; not cached, so it is tried again
                        continue
                    finally:
                        if note.status != "syncing":
                            _set(db, note, "syncing")
                    cached = ExtractedText(contenthash=src.contenthash, kind=src.kind, text=text, language=lang)
                    db.add(cached)
                    db.commit()
                if cached.text.strip():
                    texts.append((src.filename, src.kind, cached.text))
            if not texts and warnings:
                raise ExtractError(" ".join(warnings))
            _set(db, note, "processing")
            result = generate(note.course_name, note.lesson_name, texts)
            db.refresh(note)
            note.title, note.summary = result["title"], result["summary"]
            note.key_points = json.dumps(result["key_points"], ensure_ascii=False)
            note.definitions = json.dumps(result["definitions"], ensure_ascii=False)
            note.body_md = to_markdown(result, note.course_name, note.lesson_name, [(name, kind) for name, kind, _ in texts])
            note.edited = False
            note.error = ("Some files were skipped: " + " ".join(warnings)) if warnings else None
            note.generated_hash, note.generated_at = target_hash, datetime.now()   # skipped files are tried again with Regenerate
            _set(db, note, "ready")
        except (ExtractError, TranscribeError, NotesError, LLMUnavailableError) as exc:
            db.rollback()
            note = db.get(LessonNote, note_id)
            if note is not None:
                note.error = str(exc)
                _set(db, note, "error")
        except Exception as exc:
            db.rollback()
            logger.exception("Smart Notes: unexpected error on lesson %s", note_id)
            note = db.get(LessonNote, note_id)
            if note is not None:
                note.error = f"Unexpected error: {exc.__class__.__name__}: {exc}"
                _set(db, note, "error")
    finally:
        db.close()
