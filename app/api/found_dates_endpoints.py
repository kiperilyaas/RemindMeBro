"""
Exam dates found in course files (Free plan): "Find exam dates" button, review list, accept or reject.

Nothing reaches the calendar without the student: a found date is a proposal until "Add to calendar".
The same date found in two files of the course is shown once (accepting or rejecting it covers both).
"""
from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.database.db import get_db
from app.database.models import Course, Deadline, Event, FoundDateChoice, FoundExamDate, SourceType, User, UserRole
from app.services.exam_dates import scan
from app.services.exam_dates.finder import KIND_LABEL
from app.services.my_courses import student_course_codes

router = APIRouter(prefix="/api/found-dates", tags=["Exam dates in course files (Free)"])
Authenticated = Depends(get_current_user)
EXAM_WORDS = ("exam", "midterm", "mid-term", "mid term", "test", "quiz")


def _visible(db: Session, user: User) -> List[FoundExamDate]:
    codes = None if user.role == UserRole.PROFESSOR else student_course_codes(db, user)
    q = select(FoundExamDate).where(FoundExamDate.on_date >= datetime.combine(settings.reference_now().date(), time.min))
    if codes is not None:
        q = q.where(FoundExamDate.course_code.in_(codes or {""}))
    return list(db.scalars(q.order_by(FoundExamDate.on_date, FoundExamDate.id)))


def _groups(rows: List[FoundExamDate]) -> List[List[FoundExamDate]]:
    """The same event found in more files of a course: one group (same course, kind, day and time)."""
    out: Dict[Tuple, List[FoundExamDate]] = {}
    for r in rows:
        out.setdefault((r.course_code, r.kind, r.on_date.date(), r.at_time), []).append(r)
    return list(out.values())


def _in_calendar(db: Session, user: User, r: FoundExamDate, course: Optional[Course]) -> Optional[str]:
    """An official date the student already has that day for the same course (UniLearn assignment, UniSIS exam)."""
    if course is None:
        return None
    day0 = r.on_date.replace(hour=0, minute=0)
    day1 = r.on_date.replace(hour=23, minute=59, second=59)
    d = db.scalar(select(Deadline).where(Deadline.course_id == course.id, Deadline.found_in.is_(None),
                                         or_(Deadline.user_id.is_(None), Deadline.user_id == user.id),
                                         Deadline.due_date >= day0, Deadline.due_date <= day1))
    if d is not None:
        return d.title
    e = db.scalar(select(Event).where(Event.course_id == course.id, Event.kind == "exam",
                                      or_(Event.user_id.is_(None), Event.user_id == user.id),
                                      Event.start_time >= day0, Event.start_time <= day1))
    return e.title if e is not None else None


def _out(db: Session, user: User, group: List[FoundExamDate], choice: Optional[FoundDateChoice] = None) -> Dict[str, Any]:
    r = group[0]
    course = db.scalar(select(Course).where(Course.code == r.course_code))
    return {
        "id": r.id, "course_code": r.course_code, "course_name": course.name if course else r.course_code,
        "kind": r.kind, "kind_label": KIND_LABEL.get(r.kind, r.kind), "title": r.title,
        "date": r.on_date.date().isoformat(), "time": r.at_time, "room": r.room, "year_written": r.year_written,
        "quote": r.quote, "filename": r.filename, "page": r.page,
        "also_in": [{"filename": x.filename, "page": x.page} for x in group[1:]],
        "in_calendar": _in_calendar(db, user, r, course),
        "choice": choice.choice if choice else None, "deadline_id": choice.deadline_id if choice else None,
    }


@router.get("", summary="Status of the search and the dates to review")
def found_dates(db: Session = Depends(get_db), user: User = Authenticated) -> Dict[str, Any]:
    choices = {c.found_id: c for c in db.scalars(select(FoundDateChoice).where(FoundDateChoice.user_id == user.id))}
    pending, accepted = [], 0
    for g in _groups(_visible(db, user)):
        decided = next((choices[x.id] for x in g if x.id in choices), None)
        if decided is None:
            pending.append(_out(db, user, g))
        elif decided.choice == "accepted":
            accepted += 1
    st = scan.status(user.id)
    return {"status": st, "pending": pending, "accepted": accepted}


@router.post("/scan", summary="Find exam dates in the files of my courses (runs in the background)")
def start_scan(user: User = Authenticated) -> Dict[str, Any]:
    return scan.start(user.id)


def _group_of(db: Session, user: User, found_id: int) -> List[FoundExamDate]:
    for g in _groups(_visible(db, user)):
        if any(x.id == found_id for x in g):
            return g
    raise HTTPException(status_code=404, detail="Date not found.")


def _choose(db: Session, user: User, group: List[FoundExamDate], choice: str, deadline_id: Optional[int] = None) -> None:
    for x in group:
        row = db.scalar(select(FoundDateChoice).where(FoundDateChoice.user_id == user.id, FoundDateChoice.found_id == x.id))
        if row is None:
            row = FoundDateChoice(user_id=user.id, found_id=x.id)
            db.add(row)
        row.choice, row.deadline_id, row.decided_at = choice, deadline_id, datetime.now()


@router.post("/{found_id}/accept", summary="Add a found date to my calendar")
def accept(found_id: int, db: Session = Depends(get_db), user: User = Authenticated) -> Dict[str, Any]:
    group = _group_of(db, user, found_id)
    r = group[0]
    course = db.scalar(select(Course).where(Course.code == r.course_code))
    when = datetime.combine(r.on_date.date(), datetime.strptime(r.at_time, "%H:%M").time() if r.at_time else time(23, 59))
    title = r.title
    if r.kind in ("exam", "midterm", "test") and not any(w in title.lower() for w in EXAM_WORDS):
        title = f"{KIND_LABEL[r.kind]}: {title}"     # the calendar shows it with the "Exam" tag
    where = " · ".join(x for x in (r.filename, r.page.lower() if r.page else "", f"room {r.room}" if r.room else "") if x)
    d = Deadline(user_id=user.id, course_id=course.id if course else None, title=title[:255], description=r.quote,
                 due_date=when, source=SourceType.MOODLE, external_id=f"found-{r.id}-{user.id}", extracted_by_ai=True,
                 is_completed=False, found_in=where[:300], time_known=bool(r.at_time))
    db.add(d)
    db.flush()
    _choose(db, user, group, "accepted", d.id)
    db.commit()
    return {"accepted": True, "deadline_id": d.id}


@router.post("/{found_id}/reject", summary="This date is not right: never propose it again")
def reject(found_id: int, db: Session = Depends(get_db), user: User = Authenticated) -> Dict[str, Any]:
    _choose(db, user, _group_of(db, user, found_id), "rejected")
    db.commit()
    return {"rejected": True}


@router.delete("/deadline/{deadline_id}", summary="Remove an accepted date from my calendar (it is proposed again)")
def remove(deadline_id: int, db: Session = Depends(get_db), user: User = Authenticated) -> Dict[str, Any]:
    d = db.get(Deadline, deadline_id)
    if d is None or d.user_id != user.id or d.found_in is None:
        raise HTTPException(status_code=404, detail="Date not found.")
    for c in db.scalars(select(FoundDateChoice).where(FoundDateChoice.user_id == user.id, FoundDateChoice.deadline_id == d.id)):
        db.delete(c)
    db.delete(d)
    db.commit()
    return {"removed": True}
