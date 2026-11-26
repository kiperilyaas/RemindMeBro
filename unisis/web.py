"""
UniSIS web portal (server-rendered): sign-in, OAuth consent screen,
student self-service and the registrar's back office.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from unisis import security, services
from unisis.api import revoke_all
from unisis.config import settings
from app.api.access import is_local_request
from unisis.db import get_db
from unisis.models import (
    AuditLog,
    AuthorizationCode,
    Consent,
    Course,
    Enrollment,
    ExamRegistration,
    ExamTerm,
    GradeRecord,
    OAuthClient,
    Term,
    Token,
    User,
)
from unisis.seed import public_url

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------
def _dt(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%a %d %b %Y, %H:%M")


def _d(value) -> str:
    if not value:
        return "—"
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime("%d %b %Y")


templates.env.filters["dt"] = _dt
templates.env.filters["d"] = _d
templates.env.globals["university"] = settings.UNIVERSITY_NAME
templates.env.globals["scope_labels"] = security.SCOPES


def render(request: Request, name: str, user: Optional[User] = None, **ctx) -> HTMLResponse:
    flashes = request.session.pop("flash", [])
    reveal = request.session.pop("reveal", None)
    return templates.TemplateResponse(
        request,
        name,
        {
            "user": user,
            "csrf": security.csrf_token(request.session),
            "flashes": flashes,
            "reveal": reveal,
            "now": settings.now(),
            **ctx,
        },
    )


def flash(request: Request, kind: str, text: str) -> None:
    request.session.setdefault("flash", []).append([kind, text])


def current_user(request: Request, db: Session) -> Optional[User]:
    uid = request.session.get("uid")
    return db.get(User, uid) if uid else None


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def safe_next(value: Optional[str]) -> str:
    """Only allow local redirects after sign-in."""
    if not value:
        return "/"
    parts = urlsplit(value)
    return value if not parts.scheme and not parts.netloc and value.startswith("/") else "/"


def check_csrf(request: Request, token: Optional[str]) -> bool:
    if security.csrf_valid(request.session, token):
        return True
    flash(request, "error", "Your session expired. Please try again.")
    return False


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return redirect("/login")
    return redirect("/staff" if user.role == "registrar" else "/student")


def quick_accounts(request: Request, db: Session) -> list:
    """Every account, for one-click sign-in while debugging. Only on the computer that runs the demo."""
    if not is_local_request(request):
        return []
    users = sorted(db.scalars(select(User)).all(), key=lambda u: (u.role != "registrar", u.full_name.lower()))
    return [{"id": u.id, "name": u.full_name, "role": "Student Office" if u.role == "registrar" else "Student",
             "username": u.username} for u in users]


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: Optional[str] = None, db: Session = Depends(get_db)):
    return render(request, "login.html", current_user(request, db), next=safe_next(next), oauth="oauth/authorize" in (next or ""),
                  quick=quick_accounts(request, db))


@router.post("/login/quick")
def login_quick(request: Request, uid: int = Form(...), next: str = Form("/"), csrf: str = Form(""), db: Session = Depends(get_db)):
    """One-click sign-in for debugging, only on the computer that runs the demo (also inside the OAuth flow)."""
    target = safe_next(next)
    if not check_csrf(request, csrf):
        return redirect(f"/login?{urlencode({'next': target})}")
    user = db.get(User, uid)
    if not is_local_request(request) or user is None:
        flash(request, "error", "Quick sign-in works only on the computer that runs the demo.")
        return redirect(f"/login?{urlencode({'next': target})}")
    request.session["uid"] = user.id
    if user.role == "registrar" and target == "/":
        return redirect("/staff")
    return redirect(target)


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    target = safe_next(next)
    if not check_csrf(request, csrf):
        return redirect(f"/login?{urlencode({'next': target})}")
    ident = username.strip().lower()
    user = db.scalar(select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident)))
    if user is None or not security.verify_password(password, user.password_hash):
        flash(request, "error", "Wrong username or password.")
        return redirect(f"/login?{urlencode({'next': target})}")
    request.session["uid"] = user.id
    if user.role == "registrar" and target == "/":
        return redirect("/staff")   # the Student Office uses the new React app
    return redirect(target)


@router.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    if check_csrf(request, csrf):
        request.session.pop("uid", None)
        flash(request, "ok", "You have been signed out.")
    return redirect("/login")


# ---------------------------------------------------------------------------
# OAuth 2.0 authorization endpoint (login + consent)
# ---------------------------------------------------------------------------
def _redirect_with(uri: str, **params) -> RedirectResponse:
    sep = "&" if "?" in uri else "?"
    return redirect(uri + sep + urlencode({k: v for k, v in params.items() if v is not None}))


@router.get("/oauth/authorize", response_class=HTMLResponse)
def authorize(
    request: Request,
    response_type: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    scope: str = "",
    state: Optional[str] = None,
    code_challenge: str = "",
    code_challenge_method: str = "",
    db: Session = Depends(get_db),
):
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    # Never redirect to an unverified URI: show the error here instead
    if client is None:
        return render(request, "error.html", current_user(request, db), title="Unknown application",
                      message=f"The application '{client_id}' is not registered in UniSIS.")
    if not security.redirect_uri_allowed(client, redirect_uri):
        return render(request, "error.html", current_user(request, db), title="Invalid redirect URI",
                      message=f"'{redirect_uri}' is not a registered redirect URI for {client.name}.")
    if response_type != "code":
        return _redirect_with(redirect_uri, error="unsupported_response_type", state=state)
    if not code_challenge or code_challenge_method != "S256":
        return _redirect_with(redirect_uri, error="invalid_request", error_description="PKCE with S256 is required", state=state)
    requested = scope.split()
    allowed = set(client.allowed_scopes.split())
    if not requested or any(s not in allowed for s in requested):
        return _redirect_with(redirect_uri, error="invalid_scope", state=state)

    user = current_user(request, db)
    if user is None:
        return redirect(f"/login?{urlencode({'next': str(request.url.path) + '?' + str(request.url.query)})}")
    if user.role != "student":
        return render(request, "error.html", user, title="Student account required",
                      message="Only students can connect apps to their UniSIS account. Sign out and sign in as a student.")
    return render(request, "consent.html", user, client=client, scopes=requested, params={
        "client_id": client_id, "redirect_uri": redirect_uri, "scope": " ".join(requested), "state": state or "",
        "code_challenge": code_challenge,
    }, return_host=urlsplit(redirect_uri).netloc)


@router.post("/oauth/authorize")
def authorize_decision(
    request: Request,
    decision: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    scope: str = Form(...),
    state: str = Form(""),
    code_challenge: str = Form(...),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    user = current_user(request, db)
    if client is None or not security.redirect_uri_allowed(client, redirect_uri) or user is None:
        return render(request, "error.html", user, title="Invalid request", message="The authorization request is no longer valid.")
    if not security.csrf_valid(request.session, csrf):
        return render(request, "error.html", user, title="Session expired", message="Please start the connection again from the app.")
    if decision != "allow":
        return _redirect_with(redirect_uri, error="access_denied", error_description="The student denied access", state=state or None)

    code = security.new_secret("usc_", 24)
    db.add(AuthorizationCode(code_hash=security.sha256(code), client_id=client.id, user_id=user.id, redirect_uri=redirect_uri,
                             scope=scope, code_challenge=code_challenge,
                             expires_at=datetime.now() + timedelta(seconds=settings.AUTH_CODE_TTL)))
    consent = db.scalar(select(Consent).where(Consent.user_id == user.id, Consent.client_id == client.id))
    if consent is None:
        db.add(Consent(user_id=user.id, client_id=client.id, scope=scope, granted_at=datetime.now()))
    else:
        consent.scope, consent.granted_at = scope, datetime.now()
    db.commit()
    return _redirect_with(redirect_uri, code=code, state=state or None)


# ---------------------------------------------------------------------------
# Student self-service
# ---------------------------------------------------------------------------
def _student(request: Request, db: Session) -> Optional[User]:
    user = current_user(request, db)
    return user if user and user.role == "student" else None


@router.get("/student", response_class=HTMLResponse)
def student_home(request: Request, db: Session = Depends(get_db)):
    user = _student(request, db)
    if user is None:
        return redirect("/login?next=/student")
    today = settings.now().date()
    monday = today - timedelta(days=today.weekday())
    week = services.timetable(db, user, monday, monday + timedelta(days=6))
    days = []
    for i in range(5):
        d = monday + timedelta(days=i)
        days.append({"date": d, "items": [x for x in week if x["start"][:10] == d.isoformat()]})
    apps = list(db.scalars(select(Consent).where(Consent.user_id == user.id)))
    return render(
        request, "student.html", user,
        profile=services.profile(db, user),
        days=days,
        exams=services.exams_for(db, user),
        reg=services.course_registration(db, user),
        transcript=services.transcript(db, user),
        apps=apps,
    )


def _student_action(request: Request, db: Session, csrf: str, fn, *args, ok: str):
    user = _student(request, db)
    if user is None:
        return redirect("/login")
    if check_csrf(request, csrf):
        try:
            fn(db, user, *args)
            db.commit()
            flash(request, "ok", ok)
        except (services.RuleError, LookupError) as exc:
            db.rollback()
            flash(request, "error", str(exc))
    return redirect("/student")


@router.post("/student/exams/{exam_id}/register")
def student_register(exam_id: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    return _student_action(request, db, csrf, services.register_exam, exam_id, ok="You are registered for the exam.")


@router.post("/student/exams/{exam_id}/cancel")
def student_cancel(exam_id: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    return _student_action(request, db, csrf, services.cancel_exam, exam_id, ok="Exam registration cancelled.")


@router.post("/student/courses/{code}/enroll")
def student_enroll(code: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    return _student_action(request, db, csrf, services.enroll, code, ok=f"Registration request for {code} saved.")


@router.post("/student/courses/{code}/drop")
def student_drop(code: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    return _student_action(request, db, csrf, services.drop, code, ok=f"You are no longer registered in {code}.")


@router.post("/student/apps/{client_id}/revoke")
def student_revoke_app(client_id: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    user = _student(request, db)
    if user is None:
        return redirect("/login")
    if check_csrf(request, csrf):
        client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
        if client:
            n = revoke_all(db, client.id, user.id)
            db.commit()
            flash(request, "ok", f"{client.name} can no longer access your UniSIS data ({n} token(s) revoked).")
    return redirect("/student")


# ---------------------------------------------------------------------------
# Registrar back office
# ---------------------------------------------------------------------------
def _registrar(request: Request, db: Session) -> Optional[User]:
    user = current_user(request, db)
    return user if user and user.role == "registrar" else None


@router.get("/admin", response_class=HTMLResponse)
def admin_home(request: Request, db: Session = Depends(get_db)):
    user = _registrar(request, db)
    if user is None:
        return redirect("/login?next=/admin")
    now = settings.now()
    exams = []
    for ex in db.scalars(select(ExamTerm).order_by(ExamTerm.starts_at)):
        exams.append({"exam": ex, "registered": services.registered_count(db, ex),
                      "status": services.window_status(ex.registration_opens_at, ex.registration_closes_at)})
    terms = [{"term": t, "status": services.window_status(t.registration_opens_at, t.registration_closes_at)}
             for t in db.scalars(select(Term).where(Term.registration_opens_at.is_not(None)).order_by(Term.starts_on))]
    since = datetime.now() - timedelta(hours=24)
    stats = {
        "students": db.scalar(select(func.count()).select_from(User).where(User.role == "student")),
        "courses": db.scalar(select(func.count()).select_from(Course).where(Course.lecturer_name != "—")),
        "open_exams": sum(1 for e in exams if e["status"] == "open"),
        "api_calls": db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.at >= since)),
    }
    courses = list(db.scalars(select(Course).where(Course.kind == "core", Course.lecturer_name != "—").order_by(Course.name)))
    default_start = (now + timedelta(days=30)).replace(hour=9, minute=0, second=0, microsecond=0)
    return render(request, "admin_home.html", user, exams=exams, terms=terms, stats=stats, courses=courses,
                  default_start=default_start.strftime("%Y-%m-%dT%H:%M"),
                  default_opens=now.strftime("%Y-%m-%dT%H:%M"),
                  default_closes=(now + timedelta(days=14)).replace(hour=23, minute=59).strftime("%Y-%m-%dT%H:%M"))


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


@router.post("/admin/terms/{term_id}/{action}")
def admin_term_window(term_id: int, action: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    if _registrar(request, db) is None:
        return redirect("/login")
    term = db.get(Term, term_id)
    if term and action in {"open", "close"} and check_csrf(request, csrf):
        _set_window(term, action)
        db.commit()
        flash(request, "ok", f"Course registration for the {term.name} is now {'open' if action == 'open' else 'closed'}.")
    return redirect("/admin")


@router.post("/admin/exams/new")
def admin_new_exam(
    request: Request,
    course_id: int = Form(...),
    title: str = Form(...),
    starts_at: str = Form(...),
    duration: int = Form(120),
    room: str = Form(...),
    capacity: int = Form(...),
    opens_at: str = Form(...),
    closes_at: str = Form(...),
    is_partial: Optional[str] = Form(None),
    csrf: str = Form(""),
    db: Session = Depends(get_db),
):
    if _registrar(request, db) is None:
        return redirect("/login")
    if not check_csrf(request, csrf):
        return redirect("/admin")
    try:
        start, opens, closes = datetime.fromisoformat(starts_at), datetime.fromisoformat(opens_at), datetime.fromisoformat(closes_at)
    except ValueError:
        flash(request, "error", "Invalid date.")
        return redirect("/admin")
    if not opens < closes <= start:
        flash(request, "error", "The registration window must open before it closes, and close before the exam starts.")
        return redirect("/admin")
    course = db.get(Course, course_id)
    if course is None or capacity < 1:
        flash(request, "error", "Choose a course and a capacity of at least 1.")
        return redirect("/admin")
    db.add(ExamTerm(course_id=course.id, title=title.strip() or "Written exam", starts_at=start, ends_at=start + timedelta(minutes=duration),
                    room=room.strip(), capacity=capacity, registration_opens_at=opens, registration_closes_at=closes,
                    is_partial=bool(is_partial)))
    db.commit()
    flash(request, "ok", f"Exam term created: {course.name} · {title} · {_dt(start)}.")
    return redirect("/admin")


@router.post("/admin/exams/{exam_id}/window/{action}")
def admin_exam_window(exam_id: int, action: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    if _registrar(request, db) is None:
        return redirect("/login")
    ex = db.get(ExamTerm, exam_id)
    if ex and action in {"open", "close"} and check_csrf(request, csrf):
        _set_window(ex, action)
        db.commit()
        flash(request, "ok", f"Registration for {ex.course.name} · {ex.title} is now {'open' if action == 'open' else 'closed'}.")
    return redirect(request.headers.get("referer") or "/admin")


@router.get("/admin/exams/{exam_id}", response_class=HTMLResponse)
def admin_exam(exam_id: int, request: Request, db: Session = Depends(get_db)):
    user = _registrar(request, db)
    if user is None:
        return redirect("/login")
    ex = db.get(ExamTerm, exam_id)
    if ex is None:
        return redirect("/admin")
    regs = sorted(ex.registrations, key=lambda r: r.user.full_name)
    grades = {g.user_id: g for g in db.scalars(select(GradeRecord).where(GradeRecord.exam_term_id == ex.id))}
    return render(request, "admin_exam.html", user, ex=ex, regs=regs, grades=grades,
                  status=services.window_status(ex.registration_opens_at, ex.registration_closes_at),
                  grade_label=services.grade_label)


@router.post("/admin/exams/{exam_id}/grades")
async def admin_exam_grades(exam_id: int, request: Request, db: Session = Depends(get_db)):
    if _registrar(request, db) is None:
        return redirect("/login")
    form = await request.form()
    if not check_csrf(request, form.get("csrf")):
        return redirect(f"/admin/exams/{exam_id}")
    ex = db.get(ExamTerm, exam_id)
    saved, errors = 0, []
    for reg in ex.registrations:
        value = form.get(f"grade_{reg.user_id}", "")
        try:
            if services.record_grade(db, ex, reg.user, value) is not None and value.strip():
                saved += 1
        except services.RuleError as exc:
            errors.append(f"{reg.user.full_name}: {exc}")
    db.commit()
    flash(request, "error" if errors else "ok", "; ".join(errors) if errors else f"{saved} grade(s) recorded and published to the students' transcripts.")
    return redirect(f"/admin/exams/{exam_id}")


@router.get("/admin/courses", response_class=HTMLResponse)
def admin_courses(request: Request, db: Session = Depends(get_db)):
    user = _registrar(request, db)
    if user is None:
        return redirect("/login")
    rows = []
    for c in db.scalars(select(Course).where(Course.lecturer_name != "—").order_by(Course.term_id, Course.name)):
        waitlisted = db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == c.id, Enrollment.status == "waitlisted"))
        rows.append({"course": c, "enrolled": services.enrolled_count(db, c), "waitlisted": waitlisted})
    return render(request, "admin_courses.html", user, rows=rows)


@router.get("/admin/students", response_class=HTMLResponse)
def admin_students(request: Request, q: str = "", db: Session = Depends(get_db)):
    user = _registrar(request, db)
    if user is None:
        return redirect("/login")
    stmt = select(User).where(User.role == "student").order_by(User.full_name)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(or_(func.lower(User.full_name).like(like), func.lower(User.student_number).like(like)))
    students = [{"user": s, "credits": services.transcript(db, s)["credits_earned"]} for s in db.scalars(stmt)]
    return render(request, "admin_students.html", user, students=students, q=q)


@router.get("/admin/apps", response_class=HTMLResponse)
def admin_apps(request: Request, db: Session = Depends(get_db)):
    user = _registrar(request, db)
    if user is None:
        return redirect("/login")
    clients = list(db.scalars(select(OAuthClient)))
    tokens = list(db.scalars(select(Token).where(Token.revoked.is_(False), Token.expires_at > datetime.now()).order_by(Token.created_at.desc()).limit(30)))
    log = list(db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(40)))
    consents = {c.id: db.scalar(select(func.count()).select_from(Consent).where(Consent.client_id == c.id)) for c in clients}
    return render(request, "admin_apps.html", user, clients=clients, tokens=tokens, log=log, consents=consents,
                  issuer=public_url(), credentials_dir=str(settings.CREDENTIALS_DIR))


@router.post("/admin/apps/{client_id}/rotate-secret")
def admin_rotate_secret(client_id: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    if _registrar(request, db) is None:
        return redirect("/login")
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    if client and check_csrf(request, csrf):
        secret = security.rotate_client_secret(client)
        db.commit()
        security.export_credentials(client, public_url(), secret=secret)
        request.session["reveal"] = {"label": f"New client secret for {client.name}", "value": secret}
    return redirect("/admin/apps")


@router.post("/admin/apps/{client_id}/rotate-key")
def admin_rotate_key(client_id: str, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    if _registrar(request, db) is None:
        return redirect("/login")
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
    if client and check_csrf(request, csrf):
        key = security.rotate_api_key(client)
        db.commit()
        security.export_credentials(client, public_url(), api_key=key)
        request.session["reveal"] = {"label": f"New API key for {client.name}", "value": key}
    return redirect("/admin/apps")


@router.post("/admin/tokens/{token_id}/revoke")
def admin_revoke_token(token_id: int, request: Request, csrf: str = Form(""), db: Session = Depends(get_db)):
    if _registrar(request, db) is None:
        return redirect("/login")
    tok = db.get(Token, token_id)
    if tok and check_csrf(request, csrf):
        tok.revoked = True
        db.commit()
        flash(request, "ok", f"Token for {tok.user.full_name} ({tok.client.name}) revoked.")
    return redirect("/admin/apps")
