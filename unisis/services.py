"""
UniSIS business rules. Used by both the REST API and the web portal, so the
same rules apply whether a student acts in UniSIS or through a connected app.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from unisis.config import settings
from unisis.models import Course, Enrollment, ExamRegistration, ExamTerm, GradeRecord, Term, User


class RuleError(Exception):
    """A business rule was violated (mapped to HTTP 409 by the API)."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def window_status(opens: Optional[datetime], closes: Optional[datetime], now: Optional[datetime] = None) -> str:
    now = now or settings.now()
    if not opens or not closes:
        return "closed"
    if now < opens:
        return "upcoming"
    if now > closes:
        return "closed"
    return "open"


# Czech grading scale: 1 is the best grade, 4 the lowest pass, 5 is a fail.
GRADE_NAMES = {1: "excellent", 2: "very good", 3: "good", 4: "satisfactory", 5: "fail"}
PASS_MARK = 4


def grade_label(record: GradeRecord) -> str:
    if record.grade is None:
        return "Pass" if record.passed else "Fail"
    return str(record.grade)


def grade_name(record: GradeRecord) -> str:
    if record.grade is None:
        return "pass" if record.passed else "fail"
    return GRADE_NAMES.get(record.grade, "")


def current_term(db: Session) -> Optional[Term]:
    today = settings.now().date()
    return db.scalar(select(Term).where(Term.starts_on <= today, Term.ends_on >= today)) or db.scalar(
        select(Term).where(Term.starts_on > today).order_by(Term.starts_on)
    )


def registration_term(db: Session) -> Optional[Term]:
    """The term whose course registration is open, upcoming or most recently closed."""
    now = settings.now()
    terms = list(db.scalars(select(Term).where(Term.registration_closes_at.is_not(None)).order_by(Term.registration_opens_at)))
    for t in terms:
        if t.registration_closes_at >= now:
            return t
    return terms[-1] if terms else None


def enrolled_count(db: Session, course: Course) -> int:
    return db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course.id, Enrollment.status == "enrolled")) or 0


def registered_count(db: Session, exam: ExamTerm) -> int:
    return db.scalar(select(func.count()).select_from(ExamRegistration).where(ExamRegistration.exam_term_id == exam.id)) or 0


# ---------------------------------------------------------------------------
# Profile, credits, transcript
# ---------------------------------------------------------------------------
def transcript(db: Session, user: User) -> Dict[str, Any]:
    records = list(db.scalars(select(GradeRecord).where(GradeRecord.user_id == user.id).order_by(GradeRecord.recorded_on)))
    passed = [r for r in records if r.passed]
    graded = [r for r in passed if r.grade is not None]
    weight = sum(r.course.credits for r in graded)
    # credit-weighted average of the passed graded exams: lower is better (1 = excellent)
    average = round(sum(r.grade * r.course.credits for r in graded) / weight, 2) if weight else None
    return {
        "records": [
            {
                "course_code": r.course.code,
                "course_name": r.course.name,
                "credits": r.course.credits,
                "grade": grade_label(r),
                "grade_name": grade_name(r),
                "grade_value": r.grade,
                "passed": r.passed,
                "date": r.recorded_on.isoformat(),
            }
            for r in records
        ],
        "credits_earned": sum(r.course.credits for r in passed),
        "weighted_average": average,
    }


def profile(db: Session, user: User) -> Dict[str, Any]:
    t = transcript(db, user)
    today = settings.now().date()
    in_progress = sum(  # courses of the term currently running (future electives are not "in progress" yet)
        e.course.credits
        for e in db.scalars(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.status == "enrolled"))
        if e.course.term.starts_on <= today <= e.course.term.ends_on
    )
    prog = user.programme
    return {
        "id": user.id,
        "student_number": user.student_number,
        "full_name": user.full_name,
        "email": user.email,
        "year_of_study": user.year_of_study,
        "programme": {"code": prog.code, "name": prog.name, "degree": prog.degree, "total_credits": prog.total_credits} if prog else None,
        "credits": {"earned": t["credits_earned"], "in_progress": in_progress, "required": prog.total_credits if prog else None},
        "weighted_average": t["weighted_average"],
        "university": settings.UNIVERSITY_NAME,
    }


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------
def timetable(db: Session, user: User, start: date, end: date) -> List[Dict[str, Any]]:
    """Weekly slots of the student's enrolled courses, expanded to concrete dates (and exams they registered for)."""
    out: List[Dict[str, Any]] = []
    enrollments = db.scalars(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.status == "enrolled"))
    for e in enrollments:
        course = e.course
        first, last = max(start, course.term.starts_on), min(end, course.term.ends_on)
        for slot in course.slots:
            day = first + timedelta(days=(slot.weekday - first.weekday()) % 7)
            while day <= last:
                out.append(
                    {
                        "id": f"slot-{slot.id}-{day.isoformat()}",
                        "type": "class",
                        "course_code": course.code,
                        "course_name": course.name,
                        "title": slot.kind,
                        "room": slot.room,
                        "start": f"{day.isoformat()}T{slot.start_time}:00",
                        "end": f"{day.isoformat()}T{slot.end_time}:00",
                    }
                )
                day += timedelta(days=7)
    regs = db.scalars(select(ExamRegistration).where(ExamRegistration.user_id == user.id))
    for r in regs:
        ex = r.exam_term
        if start <= ex.starts_at.date() <= end:
            out.append(
                {
                    "id": f"exam-{ex.id}",
                    "type": "exam",
                    "course_code": ex.course.code,
                    "course_name": ex.course.name,
                    "title": ex.title,
                    "room": ex.room,
                    "start": ex.starts_at.isoformat(timespec="seconds"),
                    "end": ex.ends_at.isoformat(timespec="seconds"),
                }
            )
    return sorted(out, key=lambda x: x["start"])


# ---------------------------------------------------------------------------
# Course registration
# ---------------------------------------------------------------------------
def _waitlist_position(db: Session, enrollment: Enrollment) -> int:
    ahead = db.scalar(
        select(func.count()).select_from(Enrollment).where(
            Enrollment.course_id == enrollment.course_id,
            Enrollment.status == "waitlisted",
            Enrollment.created_at < enrollment.created_at,
        )
    )
    return (ahead or 0) + 1


def course_offer(db: Session, user: User, course: Course) -> Dict[str, Any]:
    enrolled = enrolled_count(db, course)
    mine = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id))
    waitlisted = db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course.id, Enrollment.status == "waitlisted")) or 0
    return {
        "course_code": course.code,
        "course_name": course.name,
        "credits": course.credits,
        "lecturer": course.lecturer_name,
        "kind": course.kind,
        "description": course.description,
        "capacity": course.capacity,
        "enrolled": enrolled,
        "seats_left": max(0, course.capacity - enrolled),
        "waitlisted": waitlisted,
        "status": mine.status if mine else "none",
        "waitlist_position": _waitlist_position(db, mine) if mine and mine.status == "waitlisted" else None,
    }


def course_registration(db: Session, user: User) -> Optional[Dict[str, Any]]:
    term = registration_term(db)
    if term is None:
        return None
    offers = [course_offer(db, user, c) for c in sorted(term.courses, key=lambda c: c.name) if c.kind == "elective"]
    return {
        "term": {"code": term.code, "name": term.name, "starts_on": term.starts_on.isoformat()},
        "opens_at": term.registration_opens_at.isoformat(timespec="seconds") if term.registration_opens_at else None,
        "closes_at": term.registration_closes_at.isoformat(timespec="seconds") if term.registration_closes_at else None,
        "status": window_status(term.registration_opens_at, term.registration_closes_at),
        "electives_required": term.electives_required,
        "electives_chosen": sum(1 for o in offers if o["status"] == "enrolled"),
        "offers": offers,
    }


def enroll(db: Session, user: User, course_code: str) -> Dict[str, Any]:
    course = db.scalar(select(Course).where(Course.code == course_code))
    if course is None:
        raise LookupError(f"Course {course_code} not found.")
    term = course.term
    if window_status(term.registration_opens_at, term.registration_closes_at) != "open":
        raise RuleError(f"Course registration for the {term.name} is not open.")
    existing = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id))
    if existing:
        raise RuleError(f"You are already {existing.status} in {course.name}.")
    passed = db.scalar(select(GradeRecord).where(GradeRecord.user_id == user.id, GradeRecord.course_id == course.id, GradeRecord.passed.is_(True)))
    if passed:
        raise RuleError(f"You have already passed {course.name}.")
    status = "enrolled" if enrolled_count(db, course) < course.capacity else "waitlisted"
    db.add(Enrollment(user_id=user.id, course_id=course.id, status=status, created_at=datetime.now()))
    db.flush()
    return course_offer(db, user, course)


def drop(db: Session, user: User, course_code: str) -> Dict[str, Any]:
    course = db.scalar(select(Course).where(Course.code == course_code))
    if course is None:
        raise LookupError(f"Course {course_code} not found.")
    term = course.term
    if window_status(term.registration_opens_at, term.registration_closes_at) != "open":
        raise RuleError(f"Course registration for the {term.name} is closed: you can no longer drop {course.name}.")
    mine = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == course.id))
    if mine is None or mine.status == "completed":
        raise RuleError(f"You are not registered in {course.name}.")
    was_enrolled = mine.status == "enrolled"
    db.delete(mine)
    db.flush()
    if was_enrolled:  # promote the first student on the waiting list
        first = db.scalar(
            select(Enrollment).where(Enrollment.course_id == course.id, Enrollment.status == "waitlisted").order_by(Enrollment.created_at)
        )
        if first:
            first.status = "enrolled"
            db.flush()
    return course_offer(db, user, course)


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------
def _exam_view(db: Session, user: User, ex: ExamTerm, enrolled_ids: set, passed_ids: set, my_regs: Dict[int, ExamRegistration]) -> Dict[str, Any]:
    count = registered_count(db, ex)
    status = window_status(ex.registration_opens_at, ex.registration_closes_at)
    registered = ex.id in my_regs
    other_final = (
        not ex.is_partial
        and any(r.exam_term.course_id == ex.course_id and not r.exam_term.is_partial and r.exam_term_id != ex.id for r in my_regs.values())
    )
    reason = None
    if registered:
        reason = None
    elif ex.course_id in passed_ids:
        reason = "Already passed"
    elif ex.course_id not in enrolled_ids:
        reason = "Not enrolled in the course"
    elif status == "upcoming":
        reason = "Registration not open yet"
    elif status == "closed":
        reason = "Registration closed"
    elif count >= ex.capacity:
        reason = "No seats left"
    elif other_final:
        reason = "Registered for another term of this exam"
    return {
        "id": ex.id,
        "course_code": ex.course.code,
        "course_name": ex.course.name,
        "credits": ex.course.credits,
        "title": ex.title,
        "is_partial": ex.is_partial,
        "starts_at": ex.starts_at.isoformat(timespec="seconds"),
        "ends_at": ex.ends_at.isoformat(timespec="seconds"),
        "room": ex.room,
        "capacity": ex.capacity,
        "registered_count": count,
        "seats_left": max(0, ex.capacity - count),
        "registration_opens_at": ex.registration_opens_at.isoformat(timespec="seconds"),
        "registration_closes_at": ex.registration_closes_at.isoformat(timespec="seconds"),
        "registration_status": status,
        "registered": registered,
        "can_register": reason is None and not registered,
        "can_cancel": registered and status == "open",
        "reason": reason,
    }


def exams_for(db: Session, user: User) -> List[Dict[str, Any]]:
    enrolled_ids = {e.course_id for e in db.scalars(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.status.in_(["enrolled", "completed"])))}
    passed_ids = {g.course_id for g in db.scalars(select(GradeRecord).where(GradeRecord.user_id == user.id, GradeRecord.passed.is_(True)))}
    my_regs = {r.exam_term_id: r for r in db.scalars(select(ExamRegistration).where(ExamRegistration.user_id == user.id))}
    now = settings.now()
    exams = db.scalars(select(ExamTerm).where(ExamTerm.course_id.in_(enrolled_ids | set()), ExamTerm.ends_at >= now - timedelta(days=1)).order_by(ExamTerm.starts_at))
    return [_exam_view(db, user, ex, enrolled_ids, passed_ids, my_regs) for ex in exams]


def register_exam(db: Session, user: User, exam_id: int) -> Dict[str, Any]:
    ex = db.get(ExamTerm, exam_id)
    if ex is None:
        raise LookupError("Exam term not found.")
    view = next((e for e in exams_for(db, user) if e["id"] == exam_id), None)
    if view is None:
        raise RuleError("You can only register for exams of courses you are enrolled in.")
    if view["registered"]:
        raise RuleError(f"You are already registered for {ex.course.name} · {ex.title}.")
    if not view["can_register"]:
        raise RuleError(f"Cannot register for {ex.course.name} · {ex.title}: {view['reason'].lower()}.")
    db.add(ExamRegistration(exam_term_id=ex.id, user_id=user.id, created_at=datetime.now()))
    db.flush()
    return next(e for e in exams_for(db, user) if e["id"] == exam_id)


def cancel_exam(db: Session, user: User, exam_id: int) -> Dict[str, Any]:
    ex = db.get(ExamTerm, exam_id)
    if ex is None:
        raise LookupError("Exam term not found.")
    reg = db.scalar(select(ExamRegistration).where(ExamRegistration.exam_term_id == ex.id, ExamRegistration.user_id == user.id))
    if reg is None:
        raise RuleError("You are not registered for this exam.")
    if window_status(ex.registration_opens_at, ex.registration_closes_at) != "open":
        raise RuleError("The registration window is closed: the registration can no longer be cancelled.")
    db.delete(reg)
    db.flush()
    return next(e for e in exams_for(db, user) if e["id"] == exam_id)


# ---------------------------------------------------------------------------
# Registrar actions
# ---------------------------------------------------------------------------
def record_grade(db: Session, exam: ExamTerm, user: User, value: str) -> Optional[GradeRecord]:
    """value: '1'..'5' (Czech scale, 1 best, 5 fail), 'pass', 'fail' or '' (no grade yet)."""
    if exam.is_partial:
        raise RuleError("Grades are recorded for final exams only.")
    value = (value or "").strip().upper()
    existing = db.scalar(select(GradeRecord).where(GradeRecord.user_id == user.id, GradeRecord.exam_term_id == exam.id))
    if not value:
        return existing
    if value in {"FAIL", "F"}:
        grade, passed = 5, False
    elif value in {"PASS", "P"}:
        grade, passed = None, True            # pass/fail activities (no number)
    else:
        try:
            grade = int(value)
        except ValueError:
            raise RuleError(f"Invalid grade '{value}' (use 1 to 5: 1 is the best, 5 is a fail).")
        if not 1 <= grade <= 5:
            raise RuleError(f"Invalid grade '{value}' (use 1 to 5: 1 is the best, 5 is a fail).")
        passed = grade <= PASS_MARK
    honours = False
    record = existing or GradeRecord(user_id=user.id, course_id=exam.course_id, exam_term_id=exam.id)
    record.grade, record.honours, record.passed = grade, honours, passed
    record.recorded_on = settings.now().date()
    if existing is None:
        db.add(record)
    enrollment = db.scalar(select(Enrollment).where(Enrollment.user_id == user.id, Enrollment.course_id == exam.course_id))
    if enrollment and passed and not exam.is_partial:
        enrollment.status = "completed"
    db.flush()
    return record
