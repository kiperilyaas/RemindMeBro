"""UniLearn web portal: dashboard, course pages, teacher editing, security keys, web-service admin."""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from unilearn.config import settings
from unilearn.db import get_db
from unilearn.models import Assignment, CalendarEvent, Course, Discussion, Enrolment, ExternalToken, Submission, User, WSLog
from unilearn.ws import FUNCTIONS, pwd_context
from app.api.access import is_local_request

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["dt"] = lambda v: v.strftime("%a %d %b %Y, %H:%M") if v else "—"
templates.env.globals["site_name"] = settings.SITE_NAME


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def csrf(request: Request) -> str:
    if "csrf" not in request.session:
        request.session["csrf"] = secrets.token_urlsafe(24)
    return request.session["csrf"]


def csrf_ok(request: Request, token: Optional[str]) -> bool:
    ok = bool(token) and hmac.compare_digest(request.session.get("csrf", ""), token)
    if not ok:
        flash(request, "error", "Your session expired. Please try again.")
    return ok


def flash(request: Request, kind: str, text: str) -> None:
    request.session.setdefault("flash", []).append([kind, text])


def me(request: Request, db: Session) -> Optional[User]:
    uid = request.session.get("uid")
    return db.get(User, uid) if uid else None


def render(request: Request, name: str, user: Optional[User], **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {
        "user": user, "csrf": csrf(request), "flashes": request.session.pop("flash", []), "now": settings.now(), **ctx})


def _teaches(db: Session, user: User, course: Course) -> bool:
    return user.role == "admin" or db.scalar(select(Enrolment).where(
        Enrolment.user_id == user.id, Enrolment.course_id == course.id, Enrolment.role == "editingteacher")) is not None


def _enrolled(db: Session, user: User, course: Course) -> bool:
    return user.role == "admin" or db.scalar(select(Enrolment).where(Enrolment.user_id == user.id, Enrolment.course_id == course.id)) is not None


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------
QUICK_ROLES = {"admin": "Admin", "teacher": "Teacher", "student": "Student"}


def quick_accounts(request: Request, db: Session) -> list:
    """Every account, for one-click sign-in while debugging. Only on the computer that runs the demo."""
    if not is_local_request(request):
        return []
    order = {"teacher": 0, "admin": 1, "student": 2}
    users = sorted(db.scalars(select(User)).all(), key=lambda u: (order.get(u.role, 3), u.lastname.lower(), u.firstname.lower()))
    return [{"id": u.id, "name": u.fullname, "role": QUICK_ROLES.get(u.role, u.role), "username": u.username} for u in users]


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", db: Session = Depends(get_db)):
    return render(request, "login.html", me(request, db), next=next if next.startswith("/") and not urlsplit(next).netloc else "/",
                  quick=quick_accounts(request, db))


@router.post("/login/quick")
def login_quick(request: Request, uid: int = Form(...), next: str = Form("/"), csrf_token: str = Form("", alias="csrf"),
                db: Session = Depends(get_db)):
    """One-click sign-in for debugging, only on the computer that runs the demo."""
    target = next if next.startswith("/") and not urlsplit(next).netloc else "/"
    user = db.get(User, uid)
    if not csrf_ok(request, csrf_token) or not is_local_request(request) or user is None:
        flash(request, "error", "Quick sign-in works only on the computer that runs the demo.")
        return redirect("/login?" + urlencode({"next": target}))
    request.session["uid"] = user.id
    if user.role in {"teacher", "admin"} and target == "/":
        return redirect("/staff")
    return redirect(target)


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/"),
          csrf_token: str = Form("", alias="csrf"), db: Session = Depends(get_db)):
    target = next if next.startswith("/") and not urlsplit(next).netloc else "/"
    if not csrf_ok(request, csrf_token):
        return redirect("/login")
    ident = username.strip().lower()
    user = db.scalar(select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident)))
    if user is None or not pwd_context.verify(password, user.password_hash):
        flash(request, "error", "Invalid login, please try again.")
        return redirect("/login?" + urlencode({"next": target}))
    request.session["uid"] = user.id
    if user.role in {"teacher", "admin"} and target == "/":
        return redirect("/staff")   # staff use the new teaching app
    return redirect(target)


@router.post("/logout")
def logout(request: Request, csrf_token: str = Form("", alias="csrf")):
    if csrf_ok(request, csrf_token):
        request.session.pop("uid", None)
    return redirect("/login")


# ---------------------------------------------------------------------------
# Dashboard and courses
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = me(request, db)
    if user is None:
        return redirect("/login")
    if user.role in {"teacher", "admin"}:
        return redirect("/staff")
    if user.role == "admin":
        courses = list(db.scalars(select(Course).order_by(Course.fullname)))
    else:
        courses = [e.course for e in db.scalars(select(Enrolment).where(Enrolment.user_id == user.id))]
    now = settings.now()
    timeline = []
    for c in courses:
        for a in c.assignments:
            if a.duedate >= now - timedelta(days=1):
                sub = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.user_id == user.id))
                timeline.append({"a": a, "submitted": sub is not None})
    timeline.sort(key=lambda x: x["a"].duedate)
    return render(request, "dashboard.html", user, courses=courses, timeline=timeline)


@router.get("/course/{course_id}", response_class=HTMLResponse)
def course_page(course_id: int, request: Request, db: Session = Depends(get_db)):
    user = me(request, db)
    if user is None:
        return redirect(f"/login?next=/course/{course_id}")
    course = db.get(Course, course_id)
    if course is None or not _enrolled(db, user, course):
        flash(request, "error", "You are not enrolled in this course.")
        return redirect("/")
    teacher = _teaches(db, user, course)
    subs = {s.assignment_id: s for s in db.scalars(select(Submission).where(Submission.user_id == user.id))}
    counts = {a.id: len(a.submissions) for a in course.assignments}
    students = sum(1 for e in course.enrolments if e.role == "student")
    default_due = (settings.now() + timedelta(days=14)).replace(hour=23, minute=59, second=0, microsecond=0)
    return render(request, "course.html", user, course=course, teacher=teacher, subs=subs, counts=counts, students=students,
                  forum=course.forums[0] if course.forums else None, default_due=default_due.strftime("%Y-%m-%dT%H:%M"))


@router.post("/course/{course_id}/announce")
def announce(course_id: int, request: Request, subject: str = Form(...), message: str = Form(...),
             csrf_token: str = Form("", alias="csrf"), db: Session = Depends(get_db)):
    user = me(request, db)
    course = db.get(Course, course_id)
    if user and course and _teaches(db, user, course) and csrf_ok(request, csrf_token) and course.forums:
        db.add(Discussion(forum_id=course.forums[0].id, user_id=user.id, subject=subject.strip()[:255] or "Announcement",
                          message=message.strip(), created=settings.now()))
        db.commit()
        flash(request, "ok", "Your announcement was posted to the Announcements forum.")
    return redirect(f"/course/{course_id}")


@router.post("/course/{course_id}/assign")
def add_assignment(course_id: int, request: Request, name: str = Form(...), intro: str = Form(""), duedate: str = Form(...),
                   csrf_token: str = Form("", alias="csrf"), db: Session = Depends(get_db)):
    user = me(request, db)
    course = db.get(Course, course_id)
    if user and course and _teaches(db, user, course) and csrf_ok(request, csrf_token):
        try:
            due = datetime.fromisoformat(duedate)
        except ValueError:
            flash(request, "error", "Invalid due date.")
            return redirect(f"/course/{course_id}")
        db.add(Assignment(course_id=course.id, name=name.strip(), intro=intro.strip(), duedate=due,
                          allowsubmissionsfromdate=settings.now(), timemodified=datetime.now()))
        db.commit()
        flash(request, "ok", f"Assignment “{name.strip()}” added, due {due:%a %d %b %Y, %H:%M}.")
    return redirect(f"/course/{course_id}")


@router.post("/assign/{assign_id}/duedate")
def change_due(assign_id: int, request: Request, duedate: str = Form(...), csrf_token: str = Form("", alias="csrf"), db: Session = Depends(get_db)):
    user = me(request, db)
    a = db.get(Assignment, assign_id)
    if user and a and _teaches(db, user, a.course) and csrf_ok(request, csrf_token):
        try:
            a.duedate = datetime.fromisoformat(duedate)
        except ValueError:
            flash(request, "error", "Invalid due date.")
            return redirect(f"/course/{a.course_id}")
        a.timemodified = settings.now()
        db.commit()
        flash(request, "ok", f"Due date of “{a.name}” changed to {a.duedate:%a %d %b %Y, %H:%M}.")
    return redirect(f"/course/{a.course_id if a else ''}")


@router.post("/assign/{assign_id}/submit")
def submit(assign_id: int, request: Request, text: str = Form(""), csrf_token: str = Form("", alias="csrf"), db: Session = Depends(get_db)):
    user = me(request, db)
    a = db.get(Assignment, assign_id)
    if user and a and _enrolled(db, user, a.course) and csrf_ok(request, csrf_token):
        sub = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.user_id == user.id))
        if sub:
            db.delete(sub)
            flash(request, "ok", f"Submission for “{a.name}” removed.")
        else:
            db.add(Submission(assignment_id=a.id, user_id=user.id, status="submitted", text=text.strip(), timemodified=settings.now()))
            flash(request, "ok", f"“{a.name}” submitted for grading.")
        db.commit()
    return redirect(f"/course/{a.course_id if a else ''}")


# ---------------------------------------------------------------------------
# Security keys (user) and web services (admin)
# ---------------------------------------------------------------------------
@router.get("/user/security-keys", response_class=HTMLResponse)
def security_keys(request: Request, db: Session = Depends(get_db)):
    user = me(request, db)
    if user is None:
        return redirect("/login?next=/user/security-keys")
    tokens = list(db.scalars(select(ExternalToken).where(ExternalToken.user_id == user.id).order_by(ExternalToken.created.desc())))
    return render(request, "security_keys.html", user, tokens=tokens)


@router.post("/user/security-keys/{token_id}/reset")
def reset_key(token_id: int, request: Request, csrf_token: str = Form("", alias="csrf"), db: Session = Depends(get_db)):
    user = me(request, db)
    tok = db.get(ExternalToken, token_id)
    if user and tok and (tok.user_id == user.id or user.role == "admin") and csrf_ok(request, csrf_token):
        db.delete(tok)
        db.commit()
        flash(request, "ok", "Token deleted: apps using it can no longer access your account.")
    return redirect(request.headers.get("referer") or "/user/security-keys")


@router.get("/admin/webservices", response_class=HTMLResponse)
def admin_ws(request: Request, db: Session = Depends(get_db)):
    user = me(request, db)
    if user is None or user.role != "admin":
        return redirect("/login?next=/admin/webservices")
    tokens = list(db.scalars(select(ExternalToken).order_by(ExternalToken.created.desc()).limit(50)))
    log = list(db.scalars(select(WSLog).order_by(WSLog.id.desc()).limit(50)))
    return render(request, "admin_ws.html", user, tokens=tokens, log=log, functions=list(FUNCTIONS), base=settings.public_url())
