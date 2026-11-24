"""
UniLearn staff area (teachers and site admin): JSON API used by the React app served at /staff.

Auth: the same session cookie as the web portal. Every state-changing request must carry the header
`X-Requested-With: staff` (a cross-site form cannot set it), which protects the API from CSRF.
Teachers create their own courses; the site admin can create a course for any teacher.
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

from unilearn.config import settings
from unilearn.db import get_db
from unilearn.models import Assignment, CalendarEvent, Course, Discussion, Enrolment, ExternalToken, Forum, Submission, User, WSLog
from unilearn.ws import FUNCTIONS, pwd_context

router = APIRouter(include_in_schema=False)
STAFF_PAGE = Path(__file__).parent / "static" / "staff" / "index.html"
STAFF_ROLES = {"teacher", "admin"}


# ---------------------------------------------------------------------------
# Page + auth helpers
# ---------------------------------------------------------------------------
@router.get("/staff", response_class=HTMLResponse)
@router.get("/staff/", response_class=HTMLResponse)
def staff_page():
    if STAFF_PAGE.is_file():
        return FileResponse(STAFF_PAGE, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<p>The staff app is not built. Run <code>npm run build</code> in <code>web/</code>.</p>", status_code=503)


def _guard(request: Request) -> None:
    if request.method != "GET" and request.headers.get("x-requested-with") != "staff":
        raise HTTPException(403, "Missing X-Requested-With header.")


def staff_user(request: Request, db: Session = Depends(get_db)) -> User:
    _guard(request)
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    if user is None or user.role not in STAFF_ROLES:
        raise HTTPException(401, "Sign in with a teacher or admin account.")
    return user


def _me(u: User) -> Dict[str, Any]:
    return {"id": u.id, "username": u.username, "fullname": u.fullname, "role": u.role}


def _my_courses(db: Session, user: User) -> List[Course]:
    if user.role == "admin":
        return list(db.scalars(select(Course).order_by(Course.fullname)))
    ids = select(Enrolment.course_id).where(Enrolment.user_id == user.id, Enrolment.role == "editingteacher")
    return list(db.scalars(select(Course).where(Course.id.in_(ids)).order_by(Course.fullname)))


def _course_for(db: Session, user: User, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if course is None or course not in _my_courses(db, user):
        raise HTTPException(404, "Course not found.")
    return course


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat(timespec="minutes") if dt else None


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
    if user is None or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(400, "Wrong username or password.")
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "This area is for teachers and the site admin. Students use the UniLearn dashboard.")
    request.session["uid"] = user.id
    return _me(user)


@router.post("/staff/api/logout")
def logout(request: Request):
    _guard(request)
    request.session.pop("uid", None)
    return {"ok": True}


@router.get("/staff/api/me")
def me(user: User = Depends(staff_user)):
    return {**_me(user), "site": settings.SITE_NAME, "now": _iso(settings.now()), "hub_url": os.getenv("RMB_HUB_URL", "http://127.0.0.1:8000/")}


@router.get("/staff/api/session")
def session(request: Request, db: Session = Depends(get_db)):
    """Like /me but never 401: {"user": null} when nobody (or a student) is signed in."""
    uid = request.session.get("uid")
    user = db.get(User, uid) if uid else None
    return {"user": me(user) if user and user.role in STAFF_ROLES else None}


@router.get("/staff/api/demo-accounts")
def demo_accounts(db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.role.in_(STAFF_ROLES)).order_by(User.role.desc(), User.lastname))
    return {"password": None, "accounts": [_me(u) for u in rows], "passwords_file": "data/STAFF-PASSWORDS.txt"}


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------
def _course_summary(db: Session, c: Course) -> Dict[str, Any]:
    students = sum(1 for e in c.enrolments if e.role == "student")
    now = settings.now()
    upcoming = [a for a in c.assignments if a.duedate >= now]
    return {
        "id": c.id, "shortname": c.shortname, "fullname": c.fullname, "summary": c.summary, "room": c.room or "",
        "teachers": [t.fullname for t in c.teachers()], "students": students,
        "assignments": len(c.assignments), "announcements": sum(len(f.discussions) for f in c.forums),
        "next_due": {"name": upcoming[0].name, "duedate": _iso(upcoming[0].duedate)} if upcoming else None,
    }


@router.get("/staff/api/courses")
def courses(user: User = Depends(staff_user), db: Session = Depends(get_db)):
    return [_course_summary(db, c) for c in _my_courses(db, user)]


@router.get("/staff/api/courses/{course_id}")
def course_detail(course_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    students = sum(1 for e in c.enrolments if e.role == "student")
    forum = c.forums[0] if c.forums else None
    return {
        **_course_summary(db, c),
        "assignment_list": [{"id": a.id, "name": a.name, "intro": a.intro, "duedate": _iso(a.duedate),
                             "submitted": len(a.submissions), "students": students} for a in c.assignments],
        "announcement_list": [{"id": d.id, "subject": d.subject, "message": d.message, "created": _iso(d.created), "author": d.user.fullname}
                              for d in (forum.discussions if forum else [])],
        "events": [{"id": e.id, "name": e.name, "timestart": _iso(e.timestart), "minutes": e.duration_minutes, "location": e.location} for e in c.events],
        "student_list": sorted(({"id": e.user.id, "fullname": e.user.fullname, "username": e.user.username}
                                for e in c.enrolments if e.role == "student"), key=lambda x: x["fullname"]),
        "can_delete": user.role == "admin" or user in c.teachers(),
    }


# ---------------------------------------------------------------------------
# Creating courses, enrolments and calendar events
# ---------------------------------------------------------------------------
@router.get("/staff/api/people")
def people(user: User = Depends(staff_user), db: Session = Depends(get_db)):
    """Students (to enrol them) and teachers (the admin picks who teaches a new course)."""
    rows = list(db.scalars(select(User).where(User.role.in_(["student", "teacher"])).order_by(User.lastname, User.firstname)))
    pick = lambda role: [{"id": u.id, "fullname": u.fullname, "username": u.username} for u in rows if u.role == role]  # noqa: E731
    return {"students": pick("student"), "teachers": pick("teacher")}


class CourseBody(BaseModel):
    shortname: str = Field(..., min_length=2, max_length=50)
    fullname: str = Field(..., min_length=2, max_length=200)
    summary: str = ""
    room: str = Field("", max_length=100)
    teacher_id: Optional[int] = None          # admin only; a teacher always teaches the course they create
    enrol_all_students: bool = False      # students normally join the courses they choose in UniSIS


@router.post("/staff/api/courses", status_code=201)
def create_course(body: CourseBody, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    short = body.shortname.strip().upper()
    if db.scalar(select(Course).where(func.upper(Course.shortname) == short)):
        raise HTTPException(409, f"A course with code {short} already exists.")
    teacher = user
    if user.role == "admin":
        teacher = db.get(User, body.teacher_id) if body.teacher_id else None
        if teacher is None or teacher.role != "teacher":
            raise HTTPException(400, "Choose the teacher of the course.")
    c = Course(shortname=short, fullname=body.fullname.strip(), summary=body.summary.strip(), room=body.room.strip())
    db.add(c)
    db.flush()
    db.add(Forum(course_id=c.id, type="news", name="Announcements"))
    db.add(Enrolment(user_id=teacher.id, course_id=c.id, role="editingteacher"))
    if body.enrol_all_students:
        for s in db.scalars(select(User).where(User.role == "student")):
            db.add(Enrolment(user_id=s.id, course_id=c.id, role="student"))
    db.commit()
    return _course_summary(db, c)


class CoursePatch(BaseModel):
    shortname: Optional[str] = Field(None, min_length=2, max_length=50)
    fullname: Optional[str] = Field(None, min_length=2, max_length=200)
    summary: Optional[str] = None
    room: Optional[str] = Field(None, max_length=100)


@router.patch("/staff/api/courses/{course_id}")
def edit_course(course_id: int, body: CoursePatch, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    if body.shortname is not None:
        short = body.shortname.strip().upper()
        if short != c.shortname and db.scalar(select(Course).where(func.upper(Course.shortname) == short)):
            raise HTTPException(409, f"A course with code {short} already exists.")
        c.shortname = short
    if body.fullname is not None:
        c.fullname = body.fullname.strip()
    if body.summary is not None:
        c.summary = body.summary.strip()
    if body.room is not None:
        old, c.room = c.room or "", body.room.strip()
        for ev in c.events:   # calendar events still in the old room follow the course
            if (ev.location or "") == old and ev.timestart >= settings.now():
                ev.location = c.room
    db.commit()
    return _course_summary(db, c)


@router.delete("/staff/api/courses/{course_id}", status_code=204)
def delete_course(course_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    db.delete(c)
    db.commit()


@router.post("/staff/api/courses/{course_id}/students/{user_id}", status_code=201)
def enrol_student(course_id: int, user_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    s = db.get(User, user_id)
    if s is None or s.role != "student":
        raise HTTPException(404, "Student not found.")
    if not db.scalar(select(Enrolment).where(Enrolment.course_id == c.id, Enrolment.user_id == s.id)):
        db.add(Enrolment(user_id=s.id, course_id=c.id, role="student"))
        db.commit()
    return {"ok": True}


@router.delete("/staff/api/courses/{course_id}/students/{user_id}", status_code=204)
def unenrol_student(course_id: int, user_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    e = db.scalar(select(Enrolment).where(Enrolment.course_id == c.id, Enrolment.user_id == user_id, Enrolment.role == "student"))
    if e:
        db.delete(e)
        db.commit()


class EventBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    timestart: datetime
    minutes: int = Field(60, ge=5, le=24 * 60)
    location: str = ""


@router.post("/staff/api/courses/{course_id}/events", status_code=201)
def add_event(course_id: int, body: EventBody, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    ev = CalendarEvent(course_id=c.id, name=body.name.strip(), timestart=body.timestart, duration_minutes=body.minutes, location=body.location.strip() or c.room or "")
    db.add(ev)
    db.commit()
    return {"id": ev.id}


@router.delete("/staff/api/events/{event_id}", status_code=204)
def delete_event(event_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found.")
    _course_for(db, user, ev.course_id)
    db.delete(ev)
    db.commit()


class AnnouncementBody(BaseModel):
    subject: str = Field(..., min_length=2, max_length=255)
    message: str = Field(..., min_length=2)


@router.post("/staff/api/courses/{course_id}/announcements", status_code=201)
def post_announcement(course_id: int, body: AnnouncementBody, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    if not c.forums:
        db.add(Forum(course_id=c.id, type="news", name="Announcements"))
        db.flush()
    d = Discussion(forum_id=c.forums[0].id, user_id=user.id, subject=body.subject.strip(), message=body.message.strip(), created=settings.now())
    db.add(d)
    db.commit()
    return {"id": d.id}


@router.delete("/staff/api/announcements/{discussion_id}", status_code=204)
def delete_announcement(discussion_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    d = db.get(Discussion, discussion_id)
    if d is None:
        raise HTTPException(404, "Announcement not found.")
    _course_for(db, user, d.forum.course_id)
    db.delete(d)
    db.commit()


class AssignmentBody(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    intro: str = ""
    duedate: datetime


@router.post("/staff/api/courses/{course_id}/assignments", status_code=201)
def add_assignment(course_id: int, body: AssignmentBody, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    c = _course_for(db, user, course_id)
    a = Assignment(course_id=c.id, name=body.name.strip(), intro=body.intro.strip(), duedate=body.duedate,
                   allowsubmissionsfromdate=settings.now(), timemodified=datetime.now())
    db.add(a)
    db.commit()
    return {"id": a.id}


class DueBody(BaseModel):
    duedate: datetime


@router.patch("/staff/api/assignments/{assign_id}")
def change_due(assign_id: int, body: DueBody, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    a = db.get(Assignment, assign_id)
    if a is None:
        raise HTTPException(404, "Assignment not found.")
    _course_for(db, user, a.course_id)
    a.duedate, a.timemodified = body.duedate, settings.now()
    db.commit()
    return {"id": a.id, "duedate": _iso(a.duedate)}


@router.delete("/staff/api/assignments/{assign_id}", status_code=204)
def delete_assignment(assign_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    a = db.get(Assignment, assign_id)
    if a is None:
        raise HTTPException(404, "Assignment not found.")
    _course_for(db, user, a.course_id)
    db.delete(a)
    db.commit()


# ---------------------------------------------------------------------------
# Web services (admin)
# ---------------------------------------------------------------------------
@router.get("/staff/api/webservices")
def webservices(user: User = Depends(staff_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Only the site admin can see web services.")
    tokens = db.scalars(select(ExternalToken).order_by(ExternalToken.created.desc()).limit(50))
    log = db.scalars(select(WSLog).order_by(WSLog.id.desc()).limit(60))
    return {
        "endpoints": {"token": f"{settings.public_url()}/login/token.php", "rest": f"{settings.public_url()}/webservice/rest/server.php"},
        "functions": list(FUNCTIONS),
        "tokens": [{"id": t.id, "user": t.user.fullname, "hint": t.token_hint, "client": t.client_name, "service": t.service,
                    "created": _iso(t.created), "lastaccess": _iso(t.lastaccess)} for t in tokens],
        "log": [{"id": r.id, "at": r.at.isoformat(timespec="seconds"), "username": r.username, "function": r.function, "status": r.status} for r in log],
    }


@router.delete("/staff/api/tokens/{token_id}", status_code=204)
def delete_token(token_id: int, user: User = Depends(staff_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(403, "Only the site admin can delete tokens.")
    t = db.get(ExternalToken, token_id)
    if t:
        db.delete(t)
        db.commit()


# ---------------------------------------------------------------------------
# Demo scenarios: none (UniLearn starts empty, the old cases needed the demo courses).
# The endpoints stay so older staff pages keep working.
# ---------------------------------------------------------------------------
@router.get("/staff/api/scenarios")
def scenarios(user: User = Depends(staff_user)):
    return []


@router.post("/staff/api/scenarios/{scenario_id}/{action}")
def run_scenario(scenario_id: str, action: str, user: User = Depends(staff_user)):
    raise HTTPException(404, "Unknown scenario.")
