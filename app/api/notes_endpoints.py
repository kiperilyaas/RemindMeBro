"""
Smart Notes (Premium): study notes made from the files lecturers upload to UniLearn/Moodle.

  POST /api/notes/sync               read lessons and files from UniLearn, queue new or changed lessons
  GET  /api/notes                    courses -> lessons with their status
  GET  /api/notes/{id}               one page of notes
  PUT  /api/notes/{id}               save the student's edits (Markdown)
  POST /api/notes/{id}/regenerate    make the notes (only when the student asks: "Make notes"), or again (drops the edits)
  POST /api/notes/{id}/stop          stop making these notes (waiting or running): back to the old notes or "Not made yet"
  DELETE /api/notes/{id}             stop and delete these notes and their chat (the lesson comes back as "Not made yet"
                                     at the next sync if its files are still in UniLearn)
  GET  /api/notes/{id}/chat          saved conversation about the lesson (?source_id= for one file)
  POST /api/notes/{id}/chat          ask the AI about this lesson only, or one of its files (RAG on the uploaded text); saved
  DELETE /api/notes/{id}/chat        clear that conversation
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.premium import require_premium
from app.database.db import get_db
from app.database.models import ExtractedText, LessonChatMessage, LessonNote, User
from app.services.llm_extractor import LLMUnavailableError
from app.services.notes import lesson_chat
from app.services import unilearn_client
from app.services.my_courses import student_course_codes
from app.services.notes import worker
from app.services.notes.sync import sync_materials
from app.services.notes.transcribe import is_installed as whisper_installed
from app.services.unilearn_client import UniLearnError

router = APIRouter(prefix="/api/notes", tags=["Smart Notes (Premium)"])


def _iso(dt):
    return dt.isoformat(timespec="minutes") if dt else None


def _row(n: LessonNote) -> Dict[str, Any]:
    return {
        "id": n.id, "course_code": n.course_code, "course_name": n.course_name, "lesson": n.lesson_name, "position": n.position,
        "status": n.status, "error": n.error, "title": n.title, "summary": n.summary, "edited": n.edited,
        "new_material": n.status == "ready" and bool(n.generated_hash) and n.generated_hash != n.sources_hash,
        "updated_at": _iso(n.updated_at), "generated_at": _iso(n.generated_at),
        "sources": [{"id": s.id, "filename": s.filename, "kind": s.kind, "size": s.filesize} for s in n.sources],
    }


def _full(n: LessonNote) -> Dict[str, Any]:
    return {**_row(n), "body_md": n.body_md, "key_points": json.loads(n.key_points or "[]"), "definitions": json.loads(n.definitions or "[]")}


def _mine(db: Session, user: User, note_id: int) -> LessonNote:
    n = db.get(LessonNote, note_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notes not found.")
    return n


@router.get("", summary="Courses and lessons with their status")
def list_notes(db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    notes = list(db.scalars(select(LessonNote).where(LessonNote.user_id == user.id).order_by(LessonNote.course_name, LessonNote.position, LessonNote.id)))
    codes = student_course_codes(db, user)
    courses: Dict[str, Dict[str, Any]] = {}
    for n in notes:
        if codes is not None and n.course_code not in codes and not n.edited:
            continue   # course dropped: hide (edited notes stay visible)
        c = courses.setdefault(n.course_code, {"code": n.course_code, "name": n.course_name, "lessons": []})
        c["lessons"].append(_row(n))
    conn = unilearn_client.get_connection(db, user)
    return {
        "connected": bool(conn and conn.status == "connected"),
        "transcription": whisper_installed(),
        "courses": list(courses.values()),
    }


@router.post("/sync", summary="Look for new lessons and files in UniLearn (nothing is processed until Make notes)")
def sync_notes(db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    try:
        result = sync_materials(db, user)
    except UniLearnError as exc:
        db.rollback()
        raise HTTPException(exc.status, str(exc)) from exc
    return {**result, **list_notes(db, user)}


@router.get("/{note_id}", summary="One page of notes")
def get_note(note_id: int, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    return _full(_mine(db, user, note_id))


class EditBody(BaseModel):
    body_md: str = Field(..., max_length=200_000)


@router.put("/{note_id}", summary="Save the student's edits")
def edit_note(note_id: int, body: EditBody, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    n = _mine(db, user, note_id)
    if n.status != "ready":
        raise HTTPException(409, "These notes are still being made.")
    n.body_md, n.edited, n.updated_at = body.body_md, True, datetime.now()
    db.commit()
    return _full(n)


@router.post("/{note_id}/regenerate", summary="Make the notes again from the lesson files")
def regenerate(note_id: int, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    n = _mine(db, user, note_id)
    if worker.is_queued(n.id):
        raise HTTPException(409, "These notes are already being made.")
    n.status, n.error, n.edited, n.updated_at = "waiting", None, False, datetime.now()
    db.commit()
    worker.enqueue(n.id)
    return _full(n)


@router.post("/{note_id}/stop", summary="Stop making these notes")
def stop_notes(note_id: int, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    n = _mine(db, user, note_id)
    if not worker.stop(n.id) and n.status in ("waiting", "syncing", "transcribing", "processing"):
        # nothing is running for it (e.g. left over from an old start): just put it back
        n.status, n.error, n.updated_at = ("ready" if n.generated_hash else "new"), None, datetime.now()
        db.commit()
    db.refresh(n)
    return _full(n)


@router.delete("/{note_id}", summary="Delete these notes and their chat")
def delete_notes(note_id: int, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, bool]:
    n = _mine(db, user, note_id)
    worker.stop(n.id)
    db.delete(n)   # sources and saved chat go with it (cascade)
    db.commit()
    return {"deleted": True}


class LessonChatBody(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    source_id: Optional[int] = Field(None, description="Only this file of the lesson; empty = every file of the lesson")


def _scope(q, source_id: Optional[int]):
    return q.where(LessonChatMessage.source_id.is_(None)) if source_id is None else q.where(LessonChatMessage.source_id == source_id)


def _msg(m: LessonChatMessage) -> Dict[str, Any]:
    return {"id": m.id, "role": m.role, "content": m.content, "sources": json.loads(m.sources or "[]"), "created_at": _iso(m.created_at)}


@router.get("/{note_id}/chat", summary="Saved conversation about this lesson (or one file)")
def lesson_chat_history(note_id: int, source_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    n = _mine(db, user, note_id)
    rows = db.scalars(_scope(select(LessonChatMessage).where(LessonChatMessage.note_id == n.id), source_id).order_by(LessonChatMessage.id))
    return {"messages": [_msg(m) for m in rows]}


@router.delete("/{note_id}/chat", status_code=204, summary="Clear the conversation about this lesson (or one file)")
def lesson_chat_clear(note_id: int, source_id: Optional[int] = None, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> None:
    n = _mine(db, user, note_id)
    for m in db.scalars(_scope(select(LessonChatMessage).where(LessonChatMessage.note_id == n.id), source_id)):
        db.delete(m)
    db.commit()


@router.post("/{note_id}/chat", summary="Ask about this lesson (or one file) using only the uploaded material")
def lesson_chat_endpoint(note_id: int, body: LessonChatBody, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> Dict[str, Any]:
    n = _mine(db, user, note_id)
    sources = [s for s in n.sources if body.source_id is None or s.id == body.source_id]
    if not sources:
        raise HTTPException(404, "This file is no longer in the lesson.")
    files = []
    for s in sources:
        t = db.get(ExtractedText, s.contenthash)
        if t is not None and t.text.strip():
            files.append((s.contenthash, s.filename, s.kind, t.text))
    if not files:
        if n.status == "new":
            raise HTTPException(409, "The files of this lesson have not been read yet. Press Make notes first.")
        busy = n.status in ("waiting", "syncing", "transcribing", "processing")
        raise HTTPException(409, "The files are still being read. Try again in a moment." if busy
                            else "No readable text in this material (a scanned PDF or a recording that could not be transcribed?).")
    scope = sources[0].filename if body.source_id is not None else f"{n.course_name} · {n.lesson_name} ({len(files)} file(s))"
    past = list(db.scalars(_scope(select(LessonChatMessage).where(LessonChatMessage.note_id == n.id), body.source_id)
                           .order_by(LessonChatMessage.id.desc()).limit(6)))[::-1]
    try:
        result = lesson_chat.answer(body.question, files, [{"role": m.role, "content": m.content} for m in past], scope)
    except LLMUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except lesson_chat.LessonChatError as exc:
        raise HTTPException(409, str(exc)) from exc
    q = LessonChatMessage(note_id=n.id, source_id=body.source_id, role="user", content=body.question.strip())
    a = LessonChatMessage(note_id=n.id, source_id=body.source_id, role="assistant", content=result["answer"],
                          sources=json.dumps(result["sources"], ensure_ascii=False))
    db.add_all([q, a])
    db.commit()
    skipped = [s.filename for s in sources if s.contenthash not in {f[0] for f in files}]
    return {**result, "scope": scope, "skipped": skipped, "messages": [_msg(q), _msg(a)]}
