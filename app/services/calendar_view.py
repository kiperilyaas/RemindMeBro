"""
What a student's calendar shows, built from every source.

1. Dates the AI found in a message (Outlook, Teams, UniLearn announcement) are proposals: they reach the calendar only
   when the student confirms them (MessageDateChoice "accepted"). Until then the official date they would move stays.
2. One entry per event: the same exam (or presentation, submission) found in several places - UniSIS exam, UniLearn
   assignment, course file, message - is shown once. The most official source is kept (UniSIS > UniLearn and other
   official dates > course file > message) and the others are listed in `also_in`.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Deadline, Event, MessageDateChoice, SourceType, User, UserRole

EXAM_RE = re.compile(r"\b(exam|exams|midterm|mid-term|mid term|test|quiz|zkouska|zkouška|písemka|pisemka|esame)\b", re.I)
STOP = {"the", "and", "for", "your", "with", "from", "this", "that", "final", "course", "class", "date", "deadline", "submission",
        "submit", "due", "via", "team", "teams", "paper"}


def is_message_date(d: Deadline) -> bool:
    """A date the AI found in a message: it needs the student's confirmation."""
    return bool(d.extracted_by_ai and d.announcement_id and not d.found_in)


def choices(db: Session, user: User) -> Dict[int, str]:
    return {c.deadline_id: c.choice for c in db.scalars(select(MessageDateChoice).where(MessageDateChoice.user_id == user.id))}


def visible(db: Session, user: User, rows: Iterable[Deadline]) -> List[Deadline]:
    """Rows the student sees: message dates only if accepted; a date moved by a message only while the move is not confirmed."""
    rows = list(rows)
    if user.role == UserRole.PROFESSOR:
        return [d for d in rows if d.superseded_by_id is None]
    mine = choices(db, user)
    by_id = {d.id: d for d in rows}
    missing = {d.superseded_by_id for d in rows if d.superseded_by_id and d.superseded_by_id not in by_id}
    if missing:
        by_id.update({d.id: d for d in db.scalars(select(Deadline).where(Deadline.id.in_(missing)))})

    def active(d: Deadline) -> bool:
        return not is_message_date(d) or mine.get(d.id) == "accepted"

    out = []
    for d in rows:
        if not active(d):
            continue
        sup = by_id.get(d.superseded_by_id) if d.superseded_by_id else None
        if sup is not None and active(sup):
            continue          # moved or replaced by a date this student has: hidden
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# One entry per event
# ---------------------------------------------------------------------------
def _exam_like(title: str) -> bool:
    return bool(EXAM_RE.search(title or "")) and not re.search(r"regist|enrol|sign up", title or "", re.I)


def _tokens(title: str) -> Set[str]:
    return {t for t in re.findall(r"[a-zà-ž0-9]+", (title or "").lower()) if len(t) > 2 and t not in STOP}


def _rank(d: Deadline) -> int:
    if not d.extracted_by_ai:
        return 0          # official: UniLearn assignment, UniSIS reminder, lecturer's formal assignment
    if d.found_in:
        return 1          # written in a course file, confirmed by the student
    return 2              # found in a message, confirmed by the student


def label(d: Deadline) -> str:
    if d.found_in:
        return f"Course file · {d.found_in}"
    if d.announcement is not None:
        where = {SourceType.EMAIL: "Outlook", SourceType.TEAMS: "Teams", SourceType.MOODLE: "UniLearn announcement"}.get(d.announcement.source, "Message")
        return f"{where} · {d.announcement.author}"
    return {SourceType.MOODLE: "UniLearn", SourceType.UNISIS: "UniSIS"}.get(d.source, str(d.source.value).title())


def same_event(a_title: str, b_title: str) -> bool:
    if _exam_like(a_title) and _exam_like(b_title):
        return True
    return bool(_tokens(a_title) & _tokens(b_title))


def merge(deadlines: List[Deadline], exam_events: List[Event]) -> Tuple[List[Tuple[Deadline, List[str], Optional[Deadline]]], Dict[int, List[str]]]:
    """
    -> ([(deadline to show, also_in labels, deadline that gives the time)], {exam event id: also_in labels}).
    Same course + same day + same event (two exams, or titles that share a word) = one entry.
    A UniSIS exam event wins over every deadline of that day for the course.
    """
    event_also: Dict[int, List[str]] = {}
    left: List[Deadline] = []
    for d in deadlines:
        ev = next((e for e in exam_events if d.course_id and e.course_id == d.course_id
                   and e.start_time.date() == d.due_date.date() and _exam_like(d.title)), None)
        if ev is not None:
            event_also.setdefault(ev.id, []).append(label(d))
        else:
            left.append(d)
    groups: Dict[Tuple[Optional[int], date], List[List[Deadline]]] = {}
    for d in sorted(left, key=lambda x: (_rank(x), x.id)):
        bucket = groups.setdefault((d.course_id, d.due_date.date()), [])
        for g in bucket:
            if d.course_id is not None and same_event(g[0].title, d.title):
                g.append(d)
                break
        else:
            bucket.append([d])
    out = []
    for bucket in groups.values():
        for g in bucket:
            primary = g[0]
            timed = primary if primary.time_known else next((x for x in g if x.time_known and x.due_date.time().strftime("%H:%M") != "23:59"), primary)
            out.append((primary, [label(x) for x in g[1:]], timed))
    out.sort(key=lambda t: t[0].due_date)
    return out, event_also
