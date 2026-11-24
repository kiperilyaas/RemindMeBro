"""
Which courses a student follows: the ones chosen in UniSIS (enrolled) plus the ones joined in UniLearn.

Each connection keeps the list in its snapshot ("course_codes"), written at every sync. Course-bound items
(deadlines, events, announcements) of other courses are hidden from the student; items without a course
(e.g. a UniSIS registration reminder) are always shown. Lecturers see everything.
"""
from __future__ import annotations

import json
from typing import Any, Optional, Set

from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from app.database.models import Connection, Course, UserRole


def student_course_codes(db: Session, user: Any) -> Optional[Set[str]]:
    """Course codes the student follows; None = unknown (a connection made before this was tracked: show everything)."""
    conns = list(db.scalars(select(Connection).where(Connection.user_id == user.id, Connection.status == "connected")))
    if not conns:
        return set()   # nothing connected and nothing chosen yet
    codes: Set[str] = set()
    known = False
    for c in conns:
        try:
            snap = json.loads(c.snapshot) if c.snapshot else {}
        except ValueError:
            snap = {}
        if "course_codes" in snap:
            known = True
            codes |= {str(x).upper() for x in snap["course_codes"]}
    return codes if known else None


def course_filter(db: Session, user: Any, course_id_column):
    """SQL condition: the row has no course, or its course is one the student follows."""
    if user is None or getattr(user, "role", None) == UserRole.PROFESSOR:
        return true()
    codes = student_course_codes(db, user)
    if codes is None:
        return true()
    return or_(course_id_column.is_(None), course_id_column.in_(select(Course.id).where(Course.code.in_(codes))))
