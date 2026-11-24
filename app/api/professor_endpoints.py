"""
Endpoint riservati al ruolo Docente (`professor`).

  GET    /api/professor/courses                       corsi gestiti (con statistiche)
  POST   /api/professor/courses                       crea un nuovo corso
  POST   /api/professor/announcements                 pubblica un avviso -> pipeline AI automatica
  GET    /api/professor/announcements                 avvisi pubblicati dal docente
  POST   /api/professor/assignments                   crea un compito formale (con scadenza)
  GET    /api/professor/extracted-deadlines           scadenze estratte dall'AI dai suoi messaggi
  PATCH  /api/professor/extracted-deadlines/{id}      corregge una scadenza estratta
  DELETE /api/professor/extracted-deadlines/{id}      scarta una scadenza estratta errata
"""
from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.api import schemas
from app.api.auth import require_professor
from app.api.endpoints import serialize_deadlines
from app.config import settings
from app.database.db import get_db
from app.database.models import Announcement, Course, Deadline, SourceType, User
from app.services import sync_service

router = APIRouter(prefix="/api/professor", tags=["Lecturer"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _own_course(db: Session, user: User, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found.")
    if course.professor_id != user.id:
        raise HTTPException(status_code=403, detail="You can only manage your own courses.")
    return course


def _own_extracted_deadline(db: Session, user: User, deadline_id: int) -> Deadline:
    d = db.get(Deadline, deadline_id)
    if d is None or not d.extracted_by_ai:
        raise HTTPException(status_code=404, detail="Extracted deadline not found.")
    owns_course = d.course is not None and d.course.professor_id == user.id
    owns_message = d.announcement is not None and d.announcement.author_id == user.id
    if not (owns_course or owns_message):
        raise HTTPException(status_code=403, detail="This deadline does not come from your messages or courses.")
    return d


# ---------------------------------------------------------------------------
# Corsi
# ---------------------------------------------------------------------------
@router.get("/courses", response_model=List[schemas.CourseWithStats], summary="Courses managed by the lecturer")
def my_courses(db: Session = Depends(get_db), user: User = Depends(require_professor)) -> List[schemas.CourseWithStats]:
    now = settings.reference_now()
    out: List[schemas.CourseWithStats] = []
    for c in db.scalars(select(Course).where(Course.professor_id == user.id).order_by(Course.name)):
        active = [d for d in c.deadlines if d.superseded_by_id is None and d.user_id is None]
        upcoming = sorted((d for d in active if d.due_date >= now), key=lambda d: d.due_date)
        item = schemas.CourseWithStats.model_validate(c)
        item.deadline_count = len(active)
        item.ai_deadline_count = sum(1 for d in active if d.extracted_by_ai)
        item.announcement_count = len(c.announcements)
        item.next_deadline = serialize_deadlines(db, upcoming[:1])[0] if upcoming else None
        out.append(item)
    return out


@router.post("/courses", response_model=schemas.CourseOut, status_code=201, summary="Create a new course")
def create_course(payload: schemas.CourseCreate, db: Session = Depends(get_db), user: User = Depends(require_professor)) -> Course:
    code = payload.code.strip().upper()
    course = db.scalar(select(Course).where(func.upper(Course.code) == code))
    if course is not None and course.professor_id not in (None, user.id):
        raise HTTPException(status_code=409, detail=f"A course with code {code} already exists.")
    if course is None:   # otherwise: the course came from UniLearn/UniSIS and nobody teaches it in the hub yet
        course = Course(code=code)
        db.add(course)
    course.name, course.professor, course.professor_id = payload.name.strip(), user.full_name, user.id
    db.commit()
    db.refresh(course)
    return course


# ---------------------------------------------------------------------------
# Avvisi -> pipeline AI
# ---------------------------------------------------------------------------
@router.post(
    "/announcements",
    response_model=schemas.ProfessorAnnouncementResponse,
    status_code=201,
    summary="Post an announcement (Teams/Moodle/email simulator) with automatic AI extraction",
)
def publish_announcement(
    payload: schemas.ProfessorAnnouncementRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_professor),
) -> schemas.ProfessorAnnouncementResponse:
    """
    1. Saves the announcement in SQLite and indexes it in ChromaDB (immediately searchable by the chat).
    2. llama3.2 reads the text: if it finds a deadline it creates/updates it in SQLite,
       linked to the lecturer's course; if it moves an existing assignment, this is reported.
    The announcement is saved even when Ollama is unavailable (status `llm_unavailable`).
    """
    course = _own_course(db, user, payload.course_id)
    detail = sync_service.process_informal_message(
        db,
        external_id=f"prof-{user.id}-{uuid.uuid4().hex[:10]}",
        content=payload.content.strip(),
        author=user.full_name,
        created_at=settings.reference_now(),
        course_code=course.code,
        source=payload.channel,
        author_id=user.id,
        course_is_certain=True,
    )
    db.commit()

    ann = db.get(Announcement, detail["announcement_id"])
    saved = None
    if detail.get("saved_deadline_id"):
        saved = serialize_deadlines(db, [db.get(Deadline, detail["saved_deadline_id"])])[0]
    extraction = detail.get("extraction")
    return schemas.ProfessorAnnouncementResponse(
        announcement=schemas.AnnouncementOut.model_validate(ann),
        status=detail.get("status", "unknown"),
        extraction=schemas.ExtractionOut(**extraction) if extraction else None,
        saved_deadline=saved,
        matched_course=detail.get("matched_course"),
        updates_existing=detail.get("updates_existing"),
        raw_llm_output=detail.get("raw_llm_output"),
        indexed_in_vector_db=detail.get("indexed_in_vector_db", False),
        llm_seconds=detail.get("llm_seconds", 0.0),
        error=detail.get("error") or detail.get("vector_db_error"),
    )


@router.get("/announcements", response_model=List[schemas.AnnouncementOut], summary="Announcements posted by the lecturer")
def my_announcements(
    limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db), user: User = Depends(require_professor)
) -> List[Announcement]:
    return list(
        db.scalars(
            select(Announcement)
            .where(Announcement.author_id == user.id)
            .order_by(Announcement.created_at.desc(), Announcement.id.desc())
            .limit(limit)
        )
    )


# ---------------------------------------------------------------------------
# Compiti formali
# ---------------------------------------------------------------------------
@router.post("/assignments", response_model=schemas.DeadlineOut, status_code=201, summary="Create an assignment with a deadline")
def create_assignment(
    payload: schemas.AssignmentCreate, db: Session = Depends(get_db), user: User = Depends(require_professor)
) -> schemas.DeadlineOut:
    """The assignment is *structured* data (like a Moodle assignment): no LLM involved."""
    course = _own_course(db, user, payload.course_id)
    deadline = Deadline(
        course_id=course.id,
        title=payload.title.strip(),
        description=payload.description,
        due_date=payload.due_date.replace(tzinfo=None),
        source=SourceType.MOODLE,
        external_id=f"hub-assign-{uuid.uuid4().hex[:10]}",
        extracted_by_ai=False,
        created_by_id=user.id,
    )
    db.add(deadline)
    db.commit()
    db.refresh(deadline)
    return serialize_deadlines(db, [deadline])[0]


# ---------------------------------------------------------------------------
# Verifica delle estrazioni AI
# ---------------------------------------------------------------------------
@router.get(
    "/extracted-deadlines",
    response_model=List[schemas.DeadlineOut],
    summary="Deadlines extracted by the AI from the lecturer's messages or courses",
)
def extracted_deadlines(db: Session = Depends(get_db), user: User = Depends(require_professor)) -> List[schemas.DeadlineOut]:
    own_course_ids = select(Course.id).where(Course.professor_id == user.id)
    own_announcement_ids = select(Announcement.id).where(Announcement.author_id == user.id)
    rows = db.scalars(
        select(Deadline)
        .options(selectinload(Deadline.course), selectinload(Deadline.announcement))
        .where(Deadline.extracted_by_ai.is_(True))
        .where(or_(Deadline.course_id.in_(own_course_ids), Deadline.announcement_id.in_(own_announcement_ids)))
        .order_by(Deadline.created_at.desc(), Deadline.id.desc())
    )
    return serialize_deadlines(db, list(rows))


@router.patch("/extracted-deadlines/{deadline_id}", response_model=schemas.DeadlineOut, summary="Correct an extracted deadline")
def update_extracted_deadline(
    deadline_id: int,
    payload: schemas.DeadlineUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_professor),
) -> schemas.DeadlineOut:
    d = _own_extracted_deadline(db, user, deadline_id)
    if payload.title is not None:
        d.title = payload.title.strip()
    if payload.description is not None:
        d.description = payload.description
    if payload.due_date is not None:
        d.due_date = payload.due_date.replace(tzinfo=None)
    db.commit()
    db.refresh(d)
    return serialize_deadlines(db, [d])[0]


@router.delete("/extracted-deadlines/{deadline_id}", status_code=204, summary="Discard a wrong extracted deadline")
def delete_extracted_deadline(deadline_id: int, db: Session = Depends(get_db), user: User = Depends(require_professor)) -> None:
    d = _own_extracted_deadline(db, user, deadline_id)
    # Ripristina eventuali scadenze Moodle che questa estrazione aveva "spostato"
    for old in db.scalars(select(Deadline).where(Deadline.superseded_by_id == d.id)):
        old.superseded_by_id = None
    db.delete(d)
    db.commit()
