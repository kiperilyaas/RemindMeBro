"""
UniSIS Student Office (registrar): JSON API used by the React app served at /staff.

Auth: the portal session cookie. State-changing requests must carry `X-Requested-With: staff` (CSRF protection).
The Student Office creates courses (with timetable), enrols students and creates exam dates.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from unisis import security, services
from unisis.api import revoke_all
from unisis.config import settings
from unisis.db import get_db
from unisis.models import AuditLog, Consent, Course, Enrollment, ExamTerm, GradeRecord, OAuthClient, Term, TimetableSlot, Token, User
from unisis.seed import public_url
from app.api.access import is_local_request

router = APIRouter(include_in_schema=False)
STAFF_PAGE = Path(__file__).parent / "static" / "staff" / "index.html"
D = datetime.fromisoformat


@router.get("/staff", response_class=HTMLResponse)
@router.get("/staff/", response_class=HTMLResponse)
def staff_page():
    if STAFF_PAGE.is_file():
        return FileResponse(STAFF_PAGE, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<p>The Student Office app is not built. Run <code>npm run build</code> in <code>web/</code>.</p>", status_code=503)


def _guard(request: Request) -> None:
    if request.method != "GET" and request.headers.get("x-requested-with") != "staff":
        raise HTTPException(403, "Missing X-Requested-With header.")


def registrar(request: Request, db: Session = Depends(get_db)) -> User:
    _guard(request)
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or user.role != "registrar":
        raise HTTPException(401, "Sign in with the Student Office account.")
    return user


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="minutes") if dt else None


def _me(u: User) -> Dict[str, Any]:
    return {"id": u.id, "username": u.username, "fullname": u.full_name, "role": u.role}


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/staff/api/login")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    _guard(request)
    ident = body.username.strip().lower()
    user = db.scalar(select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident)))
    if user is None or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(400, "Wrong username or password.")
    if user.role != "registrar":
        raise HTTPException(403, "This area is for the Student Office. Students use the UniSIS student portal.")
    request.session["uid"] = user.id
    return _me(user)


@router.post("/staff/api/logout")
def logout(request: Request):
    _guard(request)
    request.session.pop("uid", None)
    return {"ok": True}


@router.get("/staff/api/me")
def me(user: User = Depends(registrar)):
    return {**_me(user), "site": settings.UNIVERSITY_NAME, "now": _iso(settings.now()), "hub_url": os.getenv("RMB_HUB_URL", "http://127.0.0.1:8000/")}


@router.get("/staff/api/session")
def session(request: Request, db: Session = Depends(get_db)):
    """Like /me but never 401: {"user": null} when nobody (or a student) is signed in."""
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    return {"user": me(user) if user and user.role == "registrar" else None}


@router.get("/staff/api/demo-accounts")
def demo_accounts(request: Request, db: Session = Depends(get_db)):
    """Student Office accounts for the sign-in page. On the computer that runs the demo they sign in with one click."""
    rows = db.scalars(select(User).where(User.role == "registrar"))
    return {"password": None, "accounts": [_me(u) for u in rows], "passwords_file": "data/STAFF-PASSWORDS.txt",
            "local": is_local_request(request)}


class QuickLoginBody(BaseModel):
    uid: int


@router.post("/staff/api/quick-login")
def quick_login(body: QuickLoginBody, request: Request, db: Session = Depends(get_db)):
    """One-click sign-in for debugging: only on the computer that runs the demo, never through a public link."""
    _guard(request)
    if not is_local_request(request):
        raise HTTPException(403, "Quick sign-in works only on the computer that runs the demo.")
    user = db.get(User, body.uid)
    if user is None or user.role != "registrar":
        raise HTTPException(404, "No such Student Office account.")
    request.session["uid"] = user.id
    return _me(user)


# ---------------------------------------------------------------------------
# Overview, exams, terms
# ---------------------------------------------------------------------------
def _exam(db: Session, ex: ExamTerm) -> Dict[str, Any]:
    return {"id": ex.id, "course_code": ex.course.code, "course_name": ex.course.name, "title": ex.title, "is_partial": ex.is_partial,
            "starts_at": _iso(ex.starts_at), "ends_at": _iso(ex.ends_at), "room": ex.room, "capacity": ex.capacity,
            "registered": services.registered_count(db, ex), "opens_at": _iso(ex.registration_opens_at),
            "closes_at": _iso(ex.registration_closes_at), "status": services.window_status(ex.registration_opens_at, ex.registration_closes_at)}


@router.get("/staff/api/overview")
def overview(user: User = Depends(registrar), db: Session = Depends(get_db)):
    exams = [_exam(db, ex) for ex in db.scalars(select(ExamTerm).order_by(ExamTerm.starts_at))]
    terms = [{"id": t.id, "name": t.name, "opens_at": _iso(t.registration_opens_at), "closes_at": _iso(t.registration_closes_at),
              "status": services.window_status(t.registration_opens_at, t.registration_closes_at), "electives_required": t.electives_required}
             for t in db.scalars(select(Term).order_by(Term.starts_on))]
    since = datetime.now() - timedelta(hours=24)
    return {
        "stats": {
            "students": db.scalar(select(func.count()).select_from(User).where(User.role == "student")),
            "courses": db.scalar(select(func.count()).select_from(Course).where(Course.lecturer_name != "—")),
            "open_windows": sum(1 for e in exams if e["status"] == "open") + sum(1 for t in terms if t["status"] == "open"),
            "api_calls_24h": db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.at >= since)),
        },
        "exams": exams, "terms": terms,
        "courses": [{"id": c.id, "code": c.code, "name": c.name} for c in db.scalars(select(Course).where(Course.lecturer_name != "—").order_by(Course.name))],
    }


def _set_window(obj, action: str) -> None:
    now = settings.now()
    if action == "open":
        obj.registration_opens_at = now - timedelta(minutes=1)
        if obj.registration_closes_at is None or obj.registration_closes_at <= now:
            obj.registration_closes_at = (now + timedelta(days=14)).replace(hour=23, minute=59, second=0, microsecond=0)
    else:
        obj.registration_closes_at = now - timedelta(minutes=1)
        if obj.registration_opens_at and obj.registration_opens_at > obj.registration_closes_at:
            obj.registration_opens_at = obj.registration_closes_at - timedelta(days=1)


@router.post("/staff/api/exams/{exam_id}/window/{action}")
def exam_window(exam_id: int, action: str, user: User = Depends(registrar), db: Session = Depends(get_db)):
    ex = db.get(ExamTerm, exam_id)
    if ex is None or action not in {"open", "close"}:
        raise HTTPException(404, "Exam not found.")
    _set_window(ex, action)
    db.commit()
    return _exam(db, ex)


@router.post("/staff/api/terms/{term_id}/window/{action}")
def term_window(term_id: int, action: str, user: User = Depends(registrar), db: Session = Depends(get_db)):
    t = db.get(Term, term_id)
    if t is None or action not in {"open", "close"}:
        raise HTTPException(404, "Term not found.")
    _set_window(t, action)
    db.commit()
    return {"ok": True}


class ExamPatch(BaseModel):
    starts_at: Optional[datetime] = None
    room: Optional[str] = Field(None, min_length=1, max_length=100)
    capacity: Optional[int] = Field(None, ge=1, le=1000)


@router.patch("/staff/api/exams/{exam_id}")
def exam_patch(exam_id: int, body: ExamPatch, user: User = Depends(registrar), db: Session = Depends(get_db)):
    ex = db.get(ExamTerm, exam_id)
    if ex is None:
        raise HTTPException(404, "Exam not found.")
    if body.starts_at:
        length = ex.ends_at - ex.starts_at
        ex.starts_at, ex.ends_at = body.starts_at, body.starts_at + length
    if body.room:
        ex.room = body.room.strip()
    if body.capacity:
        if body.capacity < services.registered_count(db, ex):
            raise HTTPException(400, "Capacity can't be lower than the students already registered.")
        ex.capacity = body.capacity
    db.commit()
    return _exam(db, ex)


class ExamCreate(BaseModel):
    course_id: int
    title: str = Field("Written exam", min_length=2, max_length=120)
    starts_at: datetime
    minutes: int = Field(120, ge=15, le=480)
    room: str = Field(..., min_length=1, max_length=100)
    capacity: int = Field(..., ge=1, le=1000)
    opens_at: datetime
    closes_at: datetime
    is_partial: bool = False


@router.post("/staff/api/exams", status_code=201)
def exam_create(body: ExamCreate, user: User = Depends(registrar), db: Session = Depends(get_db)):
    if not body.opens_at < body.closes_at <= body.starts_at:
        raise HTTPException(400, "Registration must open before it closes, and close before the exam starts.")
    course = db.get(Course, body.course_id)
    if course is None:
        raise HTTPException(404, "Course not found.")
    ex = ExamTerm(course_id=course.id, title=body.title.strip(), starts_at=body.starts_at, ends_at=body.starts_at + timedelta(minutes=body.minutes),
                  room=body.room.strip(), capacity=body.capacity, registration_opens_at=body.opens_at, registration_closes_at=body.closes_at,
                  is_partial=body.is_partial)
    db.add(ex)
    db.commit()
    return _exam(db, ex)


@router.get("/staff/api/exams/{exam_id}")
def exam_detail(exam_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    ex = db.get(ExamTerm, exam_id)
    if ex is None:
        raise HTTPException(404, "Exam not found.")
    grades = {g.user_id: g for g in db.scalars(select(GradeRecord).where(GradeRecord.exam_term_id == ex.id))}
    regs = sorted(ex.registrations, key=lambda r: r.user.full_name)
    return {**_exam(db, ex), "students": [
        {"user_id": r.user_id, "name": r.user.full_name, "student_number": r.user.student_number, "registered_at": _iso(r.created_at),
         "grade": services.grade_label(grades[r.user_id]) if r.user_id in grades else None,
         "grade_name": services.grade_name(grades[r.user_id]) if r.user_id in grades else None} for r in regs]}


@router.post("/staff/api/exams/{exam_id}/grades")
def exam_grades(exam_id: int, body: Dict[str, str], user: User = Depends(registrar), db: Session = Depends(get_db)):
    ex = db.get(ExamTerm, exam_id)
    if ex is None:
        raise HTTPException(404, "Exam not found.")
    saved = 0
    try:
        for reg in ex.registrations:
            value = body.get(str(reg.user_id), "")
            if value.strip() and services.record_grade(db, ex, reg.user, value) is not None:
                saved += 1
    except services.RuleError as exc:
        db.rollback()
        raise HTTPException(400, str(exc))
    db.commit()
    return {"saved": saved}


# ---------------------------------------------------------------------------
# Courses and students
# ---------------------------------------------------------------------------
def _promote(db: Session, course: Course) -> int:
    """Moves students from the waiting list into free seats, first come first served."""
    moved = 0
    while services.enrolled_count(db, course) < course.capacity:
        first = db.scalar(select(Enrollment).where(Enrollment.course_id == course.id, Enrollment.status == "waitlisted").order_by(Enrollment.created_at))
        if first is None:
            break
        first.status = "enrolled"
        db.flush()
        moved += 1
    return moved


def _course_row(db: Session, c: Course) -> Dict[str, Any]:
    waitlisted = db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == c.id, Enrollment.status == "waitlisted")) or 0
    return {"id": c.id, "code": c.code, "name": c.name, "term": c.term.name, "kind": c.kind, "credits": c.credits, "lecturer": c.lecturer_name, "room": c.room or "",
            "capacity": c.capacity, "enrolled": services.enrolled_count(db, c), "waitlisted": waitlisted}


@router.get("/staff/api/courses")
def courses(user: User = Depends(registrar), db: Session = Depends(get_db)):
    return [_course_row(db, c) for c in db.scalars(select(Course).where(Course.lecturer_name != "—").order_by(Course.term_id, Course.name))]


class CoursePatch(BaseModel):
    capacity: Optional[int] = Field(None, ge=1, le=1000)
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    lecturer: Optional[str] = Field(None, min_length=2, max_length=200)
    credits: Optional[int] = Field(None, ge=1, le=30)
    room: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None


@router.patch("/staff/api/courses/{course_id}")
def course_edit(course_id: int, body: CoursePatch, user: User = Depends(registrar), db: Session = Depends(get_db)):
    c = db.get(Course, course_id)
    if c is None:
        raise HTTPException(404, "Course not found.")
    moved = 0
    if body.capacity is not None:
        if body.capacity < services.enrolled_count(db, c):
            raise HTTPException(400, "Capacity can't be lower than the students already enrolled.")
        c.capacity = body.capacity
        moved = _promote(db, c)
    if body.name is not None:
        c.name = body.name.strip()
    if body.lecturer is not None:
        c.lecturer_name = body.lecturer.strip()
    if body.credits is not None:
        c.credits = body.credits
    if body.description is not None:
        c.description = body.description.strip() or None
    if body.room is not None:
        old, c.room = c.room or "", body.room.strip()
        for sl in c.slots:   # weekly classes in the old main room move with the course
            if sl.room in (old, ""):
                sl.room = c.room
    db.commit()
    return {**_course_row(db, c), "promoted": moved}


# --- creating courses ---
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class SlotBody(BaseModel):
    weekday: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    room: str = Field("", max_length=100)     # empty = the course's main room
    kind: str = Field("Lecture", min_length=1, max_length=30)


class CourseCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=32)
    name: str = Field(..., min_length=2, max_length=200)
    credits: int = Field(6, ge=1, le=30)
    term_id: int
    lecturer: str = Field(..., min_length=2, max_length=200)
    capacity: int = Field(100, ge=1, le=1000)
    kind: str = Field("core", pattern="^(core|elective)$")
    year_of_study: int = Field(1, ge=1, le=6)
    description: str = ""
    room: str = Field("", max_length=100)
    slots: List[SlotBody] = []
    enrol_all_students: bool = True       # core courses: every student is enrolled by the Student Office


def _course_detail(db: Session, c: Course) -> Dict[str, Any]:
    return {**_course_row(db, c), "term_id": c.term_id, "year_of_study": c.year_of_study, "description": c.description or "",
            "slots": [{"id": s.id, "weekday": s.weekday, "day": WEEKDAYS[s.weekday], "start_time": s.start_time, "end_time": s.end_time,
                       "room": s.room, "kind": s.kind} for s in sorted(c.slots, key=lambda s: (s.weekday, s.start_time))],
            "students": [{"id": e.user.id, "name": e.user.full_name, "student_number": e.user.student_number, "status": e.status}
                         for e in sorted(c.enrollments, key=lambda e: e.user.full_name)],
            "exams": len(c.exam_terms)}


@router.get("/staff/api/terms")
def terms(user: User = Depends(registrar), db: Session = Depends(get_db)):
    return [{"id": t.id, "code": t.code, "name": t.name, "starts_on": t.starts_on.isoformat(), "ends_on": t.ends_on.isoformat()}
            for t in db.scalars(select(Term).order_by(Term.starts_on))]


@router.post("/staff/api/courses", status_code=201)
def course_create(body: CourseCreate, user: User = Depends(registrar), db: Session = Depends(get_db)):
    code = body.code.strip().upper()
    if db.scalar(select(Course).where(func.upper(Course.code) == code)):
        raise HTTPException(409, f"A course with code {code} already exists.")
    term = db.get(Term, body.term_id)
    if term is None:
        raise HTTPException(400, "Choose a term.")
    for sl in body.slots:
        if sl.start_time >= sl.end_time:
            raise HTTPException(400, f"{WEEKDAYS[sl.weekday]}: the class must end after it starts.")
    c = Course(code=code, name=body.name.strip(), credits=body.credits, term_id=term.id, lecturer_name=body.lecturer.strip(),
               capacity=body.capacity, kind=body.kind, year_of_study=body.year_of_study, description=body.description.strip() or None,
               room=body.room.strip())
    db.add(c)
    db.flush()
    for sl in body.slots:
        room = sl.room.strip() or c.room
        if not room:
            raise HTTPException(400, f"{WEEKDAYS[sl.weekday]} {sl.start_time}: choose a room (or set the course's main room).")
        db.add(TimetableSlot(course_id=c.id, weekday=sl.weekday, start_time=sl.start_time, end_time=sl.end_time, room=room, kind=sl.kind.strip()))
    if body.enrol_all_students and body.kind == "core":
        for st in db.scalars(select(User).where(User.role == "student").order_by(User.id)):
            status = "enrolled" if services.enrolled_count(db, c) < c.capacity else "waitlisted"
            db.add(Enrollment(user_id=st.id, course_id=c.id, status=status, created_at=datetime.now()))
            db.flush()
    db.commit()
    return _course_detail(db, c)


@router.get("/staff/api/courses/{course_id}")
def course_get(course_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    c = db.get(Course, course_id)
    if c is None:
        raise HTTPException(404, "Course not found.")
    return _course_detail(db, c)


@router.delete("/staff/api/courses/{course_id}", status_code=204)
def course_delete(course_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    c = db.get(Course, course_id)
    if c is None:
        raise HTTPException(404, "Course not found.")
    for g in db.scalars(select(GradeRecord).where(GradeRecord.course_id == c.id)):
        db.delete(g)
    db.delete(c)
    db.commit()


@router.post("/staff/api/courses/{course_id}/slots", status_code=201)
def slot_add(course_id: int, body: SlotBody, user: User = Depends(registrar), db: Session = Depends(get_db)):
    c = db.get(Course, course_id)
    if c is None:
        raise HTTPException(404, "Course not found.")
    if body.start_time >= body.end_time:
        raise HTTPException(400, "The class must end after it starts.")
    room = body.room.strip() or c.room
    if not room:
        raise HTTPException(400, "Choose a room (or set the course's main room).")
    db.add(TimetableSlot(course_id=c.id, weekday=body.weekday, start_time=body.start_time, end_time=body.end_time, room=room, kind=body.kind.strip()))
    db.commit()
    return _course_detail(db, c)


class SlotRoom(BaseModel):
    room: str = Field(..., min_length=1, max_length=100)


@router.patch("/staff/api/slots/{slot_id}")
def slot_room(slot_id: int, body: SlotRoom, user: User = Depends(registrar), db: Session = Depends(get_db)):
    sl = db.get(TimetableSlot, slot_id)
    if sl is None:
        raise HTTPException(404, "Class not found.")
    sl.room = body.room.strip()
    db.commit()
    return _course_detail(db, sl.course)


@router.delete("/staff/api/slots/{slot_id}", status_code=204)
def slot_delete(slot_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    sl = db.get(TimetableSlot, slot_id)
    if sl:
        db.delete(sl)
        db.commit()


@router.post("/staff/api/courses/{course_id}/students/{user_id}", status_code=201)
def course_enrol(course_id: int, user_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    c = db.get(Course, course_id)
    st = db.get(User, user_id)
    if c is None or st is None or st.role != "student":
        raise HTTPException(404, "Course or student not found.")
    if not db.scalar(select(Enrollment).where(Enrollment.course_id == c.id, Enrollment.user_id == st.id)):
        status = "enrolled" if services.enrolled_count(db, c) < c.capacity else "waitlisted"
        db.add(Enrollment(user_id=st.id, course_id=c.id, status=status, created_at=datetime.now()))
        db.commit()
    return _course_detail(db, c)


@router.delete("/staff/api/courses/{course_id}/students/{user_id}", status_code=204)
def course_unenrol(course_id: int, user_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    c = db.get(Course, course_id)
    e = db.scalar(select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.user_id == user_id))
    if c is not None and e is not None:
        db.delete(e)
        db.flush()
        _promote(db, c)
        db.commit()


@router.get("/staff/api/students")
def students(q: str = "", user: User = Depends(registrar), db: Session = Depends(get_db)):
    stmt = select(User).where(User.role == "student").order_by(User.full_name)
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.student_number).like(like)))
    out = []
    for s in db.scalars(stmt.limit(100)):
        t = services.transcript(db, s)
        out.append({"id": s.id, "name": s.full_name, "student_number": s.student_number, "year": s.year_of_study,
                    "programme": s.programme.name if s.programme else None, "credits": t["credits_earned"], "average": t.get("weighted_average")})
    return out


# ---------------------------------------------------------------------------
# Apps & keys
# ---------------------------------------------------------------------------
@router.get("/staff/api/apps")
def apps(user: User = Depends(registrar), db: Session = Depends(get_db)):
    clients = list(db.scalars(select(OAuthClient)))
    tokens = db.scalars(select(Token).where(Token.revoked.is_(False), Token.expires_at > datetime.now()).order_by(Token.created_at.desc()).limit(30))
    log = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(60))
    return {
        "issuer": public_url(),
        "clients": [{"client_id": c.client_id, "name": c.name, "description": c.description, "secret_hint": c.secret_hint, "api_key_hint": c.api_key_hint,
                     "redirect_uris": c.redirect_uris.split(), "scopes": c.allowed_scopes.split(), "secret_rotated_at": _iso(c.secret_rotated_at),
                     "students_connected": db.scalar(select(func.count()).select_from(Consent).where(Consent.client_id == c.id))} for c in clients],
        "tokens": [{"id": t.id, "kind": t.kind, "client": t.client.name, "user": t.user.full_name, "scope": t.scope,
                    "created": _iso(t.created_at), "expires": _iso(t.expires_at), "last_used": _iso(t.last_used_at)} for t in tokens],
        "log": [{"id": r.id, "at": r.at.isoformat(timespec="seconds"), "client": r.client_name, "user": r.username, "method": r.method,
                 "path": r.path, "status": r.status_code} for r in log],
    }


@router.post("/staff/api/tokens/{token_id}/revoke")
def revoke_token(token_id: int, user: User = Depends(registrar), db: Session = Depends(get_db)):
    t = db.get(Token, token_id)
    if t is None:
        raise HTTPException(404, "Token not found.")
    t.revoked = True
    db.commit()
    return {"ok": True}


@router.post("/staff/api/apps/{client_id}/rotate/{what}")
def rotate(client_id: str, what: str, user: User = Depends(registrar), db: Session = Depends(get_db)):
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    if client is None or what not in {"secret", "key"}:
        raise HTTPException(404, "Client not found.")
    value = security.rotate_client_secret(client) if what == "secret" else security.rotate_api_key(client)
    db.commit()
    security.export_credentials(client, public_url(), **({"secret": value} if what == "secret" else {"api_key": value}))
    return {"label": f"New {'client secret' if what == 'secret' else 'API key'} for {client.name}", "value": value}


# ---------------------------------------------------------------------------
# Demo scenarios: none (UniSIS starts empty, the old cases needed the demo courses).
# Revoking Remind Me Bro's access is in Apps & keys.
# ---------------------------------------------------------------------------
@router.get("/staff/api/scenarios")
def scenarios(user: User = Depends(registrar)):
    return []


@router.post("/staff/api/scenarios/{scenario_id}/{action}")
def run_scenario(scenario_id: str, action: str, user: User = Depends(registrar)):
    raise HTTPException(404, "Unknown scenario.")
