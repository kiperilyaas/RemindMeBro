"""
Endpoint REST "studente" (dati unificati, chat RAG, sincronizzazione).

Tutti gli endpoint, tranne /api/health, richiedono un Bearer token valido
(dependency `get_current_user`, vedi app/api/auth.py).

Nota: gli endpoint che chiamano Ollama sono funzioni *sincrone* (`def`):
FastAPI le esegue in un threadpool, così l'event loop non si blocca
mentre llama3.2 genera la risposta.
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.api import schemas
from app.api.access import is_local_request
from app.api.auth import get_current_user, list_demo_accounts
from app.api.premium import require_premium
from app.config import settings
from app.database.db import get_db
from app.database.models import Announcement, Course, Deadline, DeadlineDone, Event, SourceType, User
from app.services import llm_extractor, sync_service, vector_store
from app.services.my_courses import course_filter

router = APIRouter(prefix="/api", tags=["Academic Hub"])

# Dependency riusabile: rende l'endpoint accessibile solo ad utenti autenticati
Authenticated = Depends(get_current_user)

WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _replaces_map(db: Session, deadline_ids: List[int]) -> Dict[int, Deadline]:
    """new_deadline_id -> scadenza Moodle che è stata spostata da quell'avviso."""
    if not deadline_ids:
        return {}
    rows = db.scalars(select(Deadline).where(Deadline.superseded_by_id.in_(deadline_ids)))
    return {d.superseded_by_id: d for d in rows}


def done_ids(db: Session, user: Optional[User]) -> set:
    """Shared deadlines this student ticked as done (each student has their own ticks)."""
    if user is None:
        return set()
    return set(db.scalars(select(DeadlineDone.deadline_id).where(DeadlineDone.user_id == user.id)))


def serialize_deadlines(db: Session, deadlines: List[Deadline], user: Optional[User] = None) -> List[schemas.DeadlineOut]:
    replaces = _replaces_map(db, [d.id for d in deadlines])
    out = [schemas.DeadlineOut.from_orm_deadline(d, replaces.get(d.id)) for d in deadlines]
    if user is not None:
        mine = done_ids(db, user)
        for o, d in zip(out, deadlines):
            if d.user_id is None:   # shared course deadline: done = this student's tick, not anybody's
                o.is_completed = d.id in mine
    return out


def visible_deadlines(user: User):
    """Shared course deadlines + the user's personal ones (e.g. UniSIS registration windows)."""
    return or_(Deadline.user_id.is_(None), Deadline.user_id == user.id)


def visible_events(user: User):
    return or_(Event.user_id.is_(None), Event.user_id == user.id)


def _subject_from_content(text: str, limit: int = 80) -> str:
    """Prima frase del messaggio, accorciata: usata come oggetto nella Inbox."""
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return first if len(first) <= limit else first[: limit - 1].rstrip() + "…"


def _fmt_short(dt: datetime) -> str:
    return f"{WEEKDAYS_EN[dt.weekday()]} {dt.day} {dt.strftime('%b')}, {dt.strftime('%H:%M')}"


# ---------------------------------------------------------------------------
# Sincronizzazione
# ---------------------------------------------------------------------------
@router.post("/sync", response_model=schemas.SyncSummary, summary="Run the synchronisation pipeline")
def sync(db: Session = Depends(get_db), user: User = Authenticated) -> schemas.SyncSummary:
    """
    Imports the mock data from Moodle (structured) and Teams/email (informal),
    indexes announcements in ChromaDB and uses llama3.2 to extract hidden deadlines.
    """
    summary = sync_service.run_sync_pipeline(db, user)
    _sync_smart_notes(db, user)
    return schemas.SyncSummary(**summary)


def _sync_smart_notes(db: Session, user: User) -> None:
    """Premium students: every Sync also looks for new lesson files (the notes are made in the background)."""
    if not user.is_premium or user.is_professor:
        return
    from app.services.notes.sync import sync_materials
    from app.services.unilearn_client import UniLearnError, get_connection
    conn = get_connection(db, user)
    if conn is None or conn.status != "connected":
        return
    try:
        sync_materials(db, user)
    except (UniLearnError, Exception) as exc:  # never break the main sync
        db.rollback()
        import logging
        logging.getLogger(__name__).warning("Smart Notes sync skipped: %s", exc)


# ---------------------------------------------------------------------------
# Lettura dati unificati
# ---------------------------------------------------------------------------
@router.get("/deadlines", response_model=List[schemas.DeadlineOut], summary="All deadlines, sorted by due date")
def list_deadlines(
    include_completed: bool = Query(True, description="Include completed deadlines"),
    include_superseded: bool = Query(False, description="Include Moodle dates later moved by a lecturer announcement"),
    source: Optional[SourceType] = Query(None, description="Filter by platform"),
    course_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    user: User = Authenticated,
) -> List[schemas.DeadlineOut]:
    stmt = (
        select(Deadline)
        .options(selectinload(Deadline.course), selectinload(Deadline.announcement))
        .order_by(Deadline.due_date)
    )
    stmt = stmt.where(visible_deadlines(user), course_filter(db, user, Deadline.course_id))
    if not include_superseded:
        stmt = stmt.where(Deadline.superseded_by_id.is_(None))
    if source:
        stmt = stmt.where(Deadline.source == source)
    if course_id:
        stmt = stmt.where(Deadline.course_id == course_id)
    out = serialize_deadlines(db, list(db.scalars(stmt)), user)
    return out if include_completed else [d for d in out if not d.is_completed]


@router.patch("/deadlines/{deadline_id}/complete", response_model=schemas.DeadlineOut, summary="Mark a deadline as completed")
def complete_deadline(
    deadline_id: int, completed: bool = True, db: Session = Depends(get_db), user: User = Authenticated
) -> schemas.DeadlineOut:
    deadline = db.get(Deadline, deadline_id)
    if deadline is None or (deadline.user_id is not None and deadline.user_id != user.id):
        raise HTTPException(status_code=404, detail="Deadline not found.")
    if deadline.user_id is None:   # shared course deadline: the tick belongs to this student only
        row = db.scalar(select(DeadlineDone).where(DeadlineDone.user_id == user.id, DeadlineDone.deadline_id == deadline.id))
        if completed and row is None:
            db.add(DeadlineDone(user_id=user.id, deadline_id=deadline.id))
        elif not completed and row is not None:
            db.delete(row)
    else:
        deadline.is_completed = completed
    db.commit()
    db.refresh(deadline)
    return serialize_deadlines(db, [deadline], user)[0]


@router.get("/courses", response_model=List[schemas.CourseOut], summary="Active courses")
def list_courses(db: Session = Depends(get_db), user: User = Authenticated) -> List[Course]:
    return list(db.scalars(select(Course).order_by(Course.name)))


@router.get("/inbox", response_model=List[schemas.InboxItem], summary="Unified inbox (Moodle, Teams, email)")
def inbox(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db), user: User = Authenticated) -> List[schemas.InboxItem]:
    """
    Messages from every platform with a summary based on the AI extraction:
    if a message contains a deadline, it is highlighted.
    """
    rows = db.scalars(
        select(Announcement)
        .options(selectinload(Announcement.course), selectinload(Announcement.deadlines))
        .where(course_filter(db, user, Announcement.course_id))
        .order_by(Announcement.created_at.desc())
        .limit(limit)
    )
    now = settings.reference_now()
    items: List[schemas.InboxItem] = []
    for a in rows:
        dl = next(iter(sorted(a.deadlines, key=lambda d: d.due_date)), None)
        if dl:
            summary = f"AI-detected deadline: {dl.title} — {_fmt_short(dl.due_date)}."
        else:
            summary = "No deadline detected. Informational message."
        recent = (now - a.created_at) <= timedelta(days=2)
        items.append(
            schemas.InboxItem(
                id=a.id,
                source=a.source,
                course_id=a.course_id,
                course_code=a.course.code if a.course else None,
                course_name=a.course.name if a.course else None,
                author=a.author,
                created_at=a.created_at,
                subject=_subject_from_content(a.content),
                content=a.content,
                ai_summary=summary,
                important=bool(dl) or recent,
                deadline_id=dl.id if dl else None,
                deadline_due=dl.due_date if dl else None,
            )
        )
    return items


@router.get("/schedule", response_model=List[schemas.ScheduleEvent], summary="Timetable/events in a date range")
def schedule(
    start: Optional[date] = Query(None, description="Start date (default: Monday of the current week)"),
    end: Optional[date] = Query(None, description="End date, inclusive (default: start + 6 days)"),
    db: Session = Depends(get_db),
    user: User = Authenticated,
) -> List[schemas.ScheduleEvent]:
    ref = settings.reference_now().date()
    start = start or (ref - timedelta(days=ref.weekday()))
    end = end or (start + timedelta(days=6))
    if end < start:
        raise HTTPException(status_code=422, detail="'end' must not be before 'start'.")
    rows = db.scalars(
        select(Event)
        .options(selectinload(Event.course))
        .where(visible_events(user), course_filter(db, user, Event.course_id))
        .where(Event.start_time >= datetime.combine(start, datetime.min.time()))
        .where(Event.start_time < datetime.combine(end + timedelta(days=1), datetime.min.time()))
        .order_by(Event.start_time)
    )
    return [
        schemas.ScheduleEvent(
            id=e.id,
            course_id=e.course_id,
            course_code=e.course.code if e.course else None,
            course_name=e.course.name if e.course else None,
            title=e.title,
            start_time=e.start_time,
            end_time=e.end_time,
            location=e.location,
            source=e.source,
            kind=e.kind,
        )
        for e in rows
    ]


@router.get("/announcements", response_model=List[schemas.AnnouncementOut], summary="Recent announcements (Moodle, Teams, email)")
def list_announcements(
    limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db), user: User = Authenticated
) -> List[Announcement]:
    return list(db.scalars(select(Announcement).where(course_filter(db, user, Announcement.course_id)).order_by(Announcement.created_at.desc()).limit(limit)))


@router.get("/events", response_model=List[schemas.EventOut], summary="All calendar events")
def list_events(db: Session = Depends(get_db), user: User = Authenticated) -> List[Event]:
    return list(db.scalars(select(Event).where(visible_events(user), course_filter(db, user, Event.course_id)).order_by(Event.start_time)))


# ---------------------------------------------------------------------------
# Chatbot RAG
# ---------------------------------------------------------------------------
@router.post("/chat", response_model=schemas.ChatResponse, summary="RAG academic assistant")
def chat(payload: schemas.ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_premium)) -> schemas.ChatResponse:
    try:
        result = llm_extractor.answer_student_query(payload.question, db, user)
    except llm_extractor.LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return schemas.ChatResponse(
        question=payload.question,
        answer=result["answer"],
        sources=result["sources"],
        context_used=result["context_used"] if payload.include_context else None,
    )


# ---------------------------------------------------------------------------
# Demo live: estrazione in tempo reale
# ---------------------------------------------------------------------------
@router.post(
    "/simulate-teams-message",
    response_model=schemas.SimulateMessageResponse,
    summary="Simulate a new Teams message and extract the deadline in real time",
)
def simulate_teams_message(
    payload: schemas.SimulateMessageRequest, db: Session = Depends(get_db), user: User = Authenticated
) -> schemas.SimulateMessageResponse:
    course = None
    if payload.course_code:
        course = db.scalar(select(Course).where(Course.code == payload.course_code))
        if course is None:
            raise HTTPException(status_code=404, detail=f"Course '{payload.course_code}' not found. Run POST /api/sync first.")

    message_id = f"live-{uuid.uuid4().hex[:10]}"
    ann, vector_error = sync_service.upsert_announcement(
        db,
        external_id=message_id,
        source=payload.source,
        author=payload.author,
        content=payload.content,
        created_at=settings.reference_now(),
        course=course,
    )
    db.commit()

    started = time.perf_counter()
    try:
        result = llm_extractor.extract_and_save_deadline(
            db,
            payload.content,
            source=payload.source,
            external_id=message_id,
            fallback_course_code=payload.course_code,
            announcement_id=ann.id,
        )
        db.commit()
    except llm_extractor.LLMUnavailableError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except llm_extractor.LLMParsingError as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    elapsed = round(time.perf_counter() - started, 2)

    saved = None
    if result.saved_deadline_id:
        saved = serialize_deadlines(db, [db.get(Deadline, result.saved_deadline_id)])[0]

    return schemas.SimulateMessageResponse(
        message_id=message_id,
        announcement_id=ann.id,
        indexed_in_vector_db=vector_error is None,
        extraction=schemas.ExtractionOut(**result.extraction.model_dump()),
        saved_deadline=saved,
        matched_course=result.matched_course_name,
        updates_existing=result.updates_existing,
        raw_llm_output=result.raw_llm_output,
        llm_seconds=elapsed,
    )


# ---------------------------------------------------------------------------
# Diagnostica (pubblici)
# ---------------------------------------------------------------------------
@router.get("/health", response_model=schemas.HealthOut, summary="Ollama, database and vector store status (public)")
def health() -> schemas.HealthOut:
    ollama_status = llm_extractor.check_ollama()
    return schemas.HealthOut(
        status="ok" if ollama_status.get("model_available") else "degraded",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        reference_date=settings.reference_now(),
        ollama=ollama_status,
        vector_documents=vector_store.count_documents(),
    )


@router.get("/demo-accounts", summary="Demo accounts for the login screen (public)")
def demo_accounts(request: Request, db: Session = Depends(get_db)) -> dict:
    """Demo accounts for the sign-in page. Through the public link only the demo student (one-tap sign-in), never lecturers."""
    if not settings.DEMO_SEED_USERS:
        return {"password": None, "accounts": [], "local": is_local_request(request)}
    if not is_local_request(request):
        students = [a for a in list_demo_accounts(db) if a["role"] == "student" and a["password"]]
        return {"password": None, "accounts": students, "local": False}
    return {"password": None, "accounts": list_demo_accounts(db), "local": True,
            "staff_passwords_file": "data/STAFF-PASSWORDS.txt"}
