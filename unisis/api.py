"""
UniSIS REST API (v1) and OAuth 2.0 token endpoints.

Student data: Bearer access token (Authorization Code + PKCE) with scopes.
Catalogue: X-API-Key header (application key, no student involved).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Callable, Optional, Tuple

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from unisis import security, services
from unisis.config import settings
from unisis.db import get_db
from unisis.models import AuthorizationCode, Consent, Course, OAuthClient, Token, User
from unisis.seed import public_url

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Token issuing helpers
# ---------------------------------------------------------------------------
def issue_tokens(db: Session, client: OAuthClient, user: User, scope: str) -> dict:
    access = security.new_secret("usa_")
    refresh = security.new_secret("usr_")
    now = datetime.now()
    db.add(Token(token_hash=security.sha256(access), kind="access", client_id=client.id, user_id=user.id, scope=scope,
                 expires_at=now + timedelta(seconds=settings.ACCESS_TOKEN_TTL)))
    db.add(Token(token_hash=security.sha256(refresh), kind="refresh", client_id=client.id, user_id=user.id, scope=scope,
                 expires_at=now + timedelta(seconds=settings.REFRESH_TOKEN_TTL)))
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": settings.ACCESS_TOKEN_TTL,
        "refresh_token": refresh,
        "scope": scope,
        "student_number": user.student_number,
        "full_name": user.full_name,
    }


def oauth_error(error: str, description: str, status: int = 400) -> JSONResponse:
    headers = {"WWW-Authenticate": 'Basic realm="unisis"'} if status == 401 else None
    return JSONResponse({"error": error, "error_description": description}, status_code=status, headers=headers)


def revoke_all(db: Session, client_id: int, user_id: int) -> int:
    count = 0
    for t in db.scalars(select(Token).where(Token.client_id == client_id, Token.user_id == user_id, Token.revoked.is_(False))):
        t.revoked = True
        count += 1
    consent = db.scalar(select(Consent).where(Consent.client_id == client_id, Consent.user_id == user_id))
    if consent:
        db.delete(consent)
    return count


# ---------------------------------------------------------------------------
# OAuth 2.0 endpoints
# ---------------------------------------------------------------------------
@router.get("/.well-known/oauth-authorization-server", tags=["OAuth 2.0"], summary="Authorization server metadata (RFC 8414)")
def metadata():
    base = public_url()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "revocation_endpoint": f"{base}/oauth/revoke",
        "scopes_supported": list(security.SCOPES),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
    }


def _client_from_request(db: Session, authorization: Optional[str], client_id: Optional[str], client_secret: Optional[str]) -> Optional[OAuthClient]:
    basic_id, basic_secret = security.parse_basic_auth(authorization)
    return security.authenticate_client(db, basic_id or client_id, basic_secret or client_secret)


@router.post("/oauth/token", tags=["OAuth 2.0"], summary="Exchange an authorization code or a refresh token")
def token(
    request: Request,
    grant_type: str = Form(...),
    code: Optional[str] = Form(None),
    redirect_uri: Optional[str] = Form(None),
    code_verifier: Optional[str] = Form(None),
    refresh_token: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    client = _client_from_request(db, authorization, client_id, client_secret)
    if client is None:
        return oauth_error("invalid_client", "Unknown client or wrong client secret.", 401)
    request.state.audit = (client.name, None)

    if grant_type == "authorization_code":
        if not code or not redirect_uri or not code_verifier:
            return oauth_error("invalid_request", "code, redirect_uri and code_verifier are required.")
        row = db.scalar(select(AuthorizationCode).where(AuthorizationCode.code_hash == security.sha256(code)))
        if row is None or row.used or row.client_id != client.id or row.expires_at < datetime.now():
            return oauth_error("invalid_grant", "The authorization code is invalid, expired or already used.")
        if row.redirect_uri != redirect_uri:
            return oauth_error("invalid_grant", "redirect_uri does not match the authorization request.")
        if not security.verify_pkce(code_verifier, row.code_challenge):
            return oauth_error("invalid_grant", "PKCE verification failed.")
        row.used = True
        user = db.get(User, row.user_id)
        result = issue_tokens(db, client, user, row.scope)
        request.state.audit = (client.name, user.username)
        db.commit()
        return result

    if grant_type == "refresh_token":
        if not refresh_token:
            return oauth_error("invalid_request", "refresh_token is required.")
        old = db.scalar(select(Token).where(Token.token_hash == security.sha256(refresh_token), Token.kind == "refresh"))
        if old is None or old.revoked or old.client_id != client.id or old.expires_at < datetime.now():
            return oauth_error("invalid_grant", "The refresh token is invalid, expired or revoked.")
        old.revoked = True  # rotation: every refresh token can be used once
        result = issue_tokens(db, client, old.user, old.scope)
        request.state.audit = (client.name, old.user.username)
        db.commit()
        return result

    return oauth_error("unsupported_grant_type", f"Grant type '{grant_type}' is not supported.")


@router.post("/oauth/revoke", tags=["OAuth 2.0"], summary="Revoke a token (and the app's access for that student)")
def revoke(
    request: Request,
    token: str = Form(...),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None),
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    client = _client_from_request(db, authorization, client_id, client_secret)
    if client is None:
        return oauth_error("invalid_client", "Unknown client or wrong client secret.", 401)
    row = db.scalar(select(Token).where(Token.token_hash == security.sha256(token)))
    if row and row.client_id == client.id:
        request.state.audit = (client.name, row.user.username)
        revoke_all(db, client.id, row.user_id)
        db.commit()
    return {"revoked": True}  # RFC 7009: always 200, even for unknown tokens


# ---------------------------------------------------------------------------
# Auth dependencies for the API
# ---------------------------------------------------------------------------
def require_scopes(*scopes: str) -> Callable:
    def dependency(
        request: Request,
        creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
        db: Session = Depends(get_db),
    ) -> Tuple[User, OAuthClient]:
        challenge = {"WWW-Authenticate": 'Bearer realm="unisis"'}
        if creds is None:
            raise HTTPException(401, "Missing bearer token.", headers=challenge)
        tok = db.scalar(select(Token).where(Token.token_hash == security.sha256(creds.credentials), Token.kind == "access"))
        if tok is None or tok.revoked or tok.expires_at < datetime.now():
            raise HTTPException(401, "Invalid, expired or revoked access token.", headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
        request.state.audit = (tok.client.name, tok.user.username)
        missing = [s for s in scopes if s not in tok.scope.split()]
        if missing:
            raise HTTPException(403, f"Insufficient scope: requires {' '.join(missing)}.",
                                headers={"WWW-Authenticate": f'Bearer error="insufficient_scope" scope="{" ".join(scopes)}"'})
        tok.last_used_at = datetime.now()
        db.commit()
        return tok.user, tok.client
    return dependency


def require_api_key(request: Request, x_api_key: Optional[str] = Header(None), db: Session = Depends(get_db)) -> OAuthClient:
    client = security.client_by_api_key(db, x_api_key)
    if client is None:
        raise HTTPException(401, "Missing or invalid X-API-Key header.")
    request.state.audit = (client.name, None)
    return client


def _run(db: Session, fn, *args):
    """Runs a business action and maps rule violations to HTTP errors."""
    try:
        result = fn(db, *args)
        db.commit()
        return result
    except services.RuleError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(404, str(exc))


# ---------------------------------------------------------------------------
# REST API v1
# ---------------------------------------------------------------------------
class ProvisionStudent(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=200)
    password: str = Field(..., min_length=6, max_length=72)


@router.post("/api/v1/provisioning/students", tags=["Provisioning (client credentials)"], summary="Sign a student up through a trusted app")
def provision_student(body: ProvisionStudent, authorization: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """
    Remind Me Bro signs students up: it authenticates with its client ID and secret (HTTP Basic).
    UniSIS creates the student (username = email), records the student's consent for the app
    (given on the sign-up form) and returns OAuth tokens, so the student is connected right away.
    """
    from unisis.models import Programme
    cid, secret = security.parse_basic_auth(authorization)
    client = security.authenticate_client(db, cid, secret)
    if client is None or client.client_id != settings.HUB_CLIENT_ID:
        return oauth_error("invalid_client", "Client authentication failed.", 401)
    email = body.email.lower()
    if db.scalar(select(User).where(or_(func.lower(User.email) == email, func.lower(User.username) == email))):
        return JSONResponse({"error": "conflict", "error_description": "An account with this email already exists."}, status_code=409)
    prog = db.scalar(select(Programme).order_by(Programme.id))
    year = settings.now().year
    seq = (db.scalar(select(func.count()).select_from(User).where(User.role == "student")) or 0) + 1
    number = f"EF-{year}-{1000 + seq:04d}"
    while db.scalar(select(User).where(User.student_number == number)):
        seq += 1
        number = f"EF-{year}-{1000 + seq:04d}"
    user = User(username=email, email=email, full_name=body.full_name.strip(), role="student", password_hash=security.hash_password(body.password),
                student_number=number, programme_id=prog.id if prog else None, year_of_study=1)
    db.add(user)
    db.flush()
    scope = client.allowed_scopes
    db.add(Consent(user_id=user.id, client_id=client.id, scope=scope))
    tokens = issue_tokens(db, client, user, scope)
    db.commit()
    return tokens


@router.get("/api/v1/catalogue/courses", tags=["Catalogue (API key)"], summary="Course catalogue with seats and timetable")
def catalogue(client: OAuthClient = Depends(require_api_key), db: Session = Depends(get_db)):
    out = []
    for c in db.scalars(select(Course).where(Course.lecturer_name != "—").order_by(Course.term_id, Course.name)):
        enrolled = services.enrolled_count(db, c)
        out.append({
            "code": c.code, "name": c.name, "credits": c.credits, "kind": c.kind, "term": c.term.name,
            "lecturer": c.lecturer_name, "capacity": c.capacity, "enrolled": enrolled, "seats_left": max(0, c.capacity - enrolled),
            "timetable": [{"weekday": s.weekday, "start": s.start_time, "end": s.end_time, "room": s.room, "kind": s.kind} for s in c.slots],
        })
    return out


@router.get("/api/v1/me", tags=["Student (OAuth)"], summary="Profile, programme, credits and average")
def me(auth=Depends(require_scopes("profile")), db: Session = Depends(get_db)):
    return services.profile(db, auth[0])


@router.get("/api/v1/me/timetable", tags=["Student (OAuth)"], summary="Personal timetable (default: current week)")
def my_timetable(
    from_: Optional[date] = Query(None, alias="from"),
    to: Optional[date] = Query(None),
    auth=Depends(require_scopes("timetable")),
    db: Session = Depends(get_db),
):
    today = settings.now().date()
    start = from_ or today - timedelta(days=today.weekday())
    end = to or start + timedelta(days=6)
    if (end - start).days > 200:
        raise HTTPException(422, "The range cannot exceed 200 days.")
    return services.timetable(db, auth[0], start, end)


@router.get("/api/v1/me/enrollments", tags=["Student (OAuth)"], summary="Courses the student is registered in")
def my_enrollments(auth=Depends(require_scopes("enrollments")), db: Session = Depends(get_db)):
    from unisis.models import Enrollment

    rows = db.scalars(select(Enrollment).where(Enrollment.user_id == auth[0].id))
    return [
        {"course_code": e.course.code, "course_name": e.course.name, "credits": e.course.credits, "term": e.course.term.name,
         "kind": e.course.kind, "status": e.status, "lecturer": e.course.lecturer_name}
        for e in rows
    ]


@router.get("/api/v1/me/course-registration", tags=["Student (OAuth)"], summary="Open course registration window and offers")
def my_course_registration(auth=Depends(require_scopes("enrollments")), db: Session = Depends(get_db)):
    return services.course_registration(db, auth[0])


@router.post("/api/v1/me/course-registration/{course_code}", tags=["Student (OAuth)"], summary="Enroll (or join the waiting list)")
def enroll(course_code: str, auth=Depends(require_scopes("enrollments:write")), db: Session = Depends(get_db)):
    return _run(db, services.enroll, auth[0], course_code)


@router.delete("/api/v1/me/course-registration/{course_code}", tags=["Student (OAuth)"], summary="Drop a course / leave the waiting list")
def drop(course_code: str, auth=Depends(require_scopes("enrollments:write")), db: Session = Depends(get_db)):
    return _run(db, services.drop, auth[0], course_code)


@router.get("/api/v1/me/exams", tags=["Student (OAuth)"], summary="Exam terms of the student's courses")
def my_exams(auth=Depends(require_scopes("exams")), db: Session = Depends(get_db)):
    return services.exams_for(db, auth[0])


@router.post("/api/v1/me/exams/{exam_id}/registration", tags=["Student (OAuth)"], summary="Register for an exam term")
def register_exam(exam_id: int, auth=Depends(require_scopes("exams:write")), db: Session = Depends(get_db)):
    return _run(db, services.register_exam, auth[0], exam_id)


@router.delete("/api/v1/me/exams/{exam_id}/registration", tags=["Student (OAuth)"], summary="Cancel an exam registration")
def cancel_exam(exam_id: int, auth=Depends(require_scopes("exams:write")), db: Session = Depends(get_db)):
    return _run(db, services.cancel_exam, auth[0], exam_id)


@router.get("/api/v1/me/grades", tags=["Student (OAuth)"], summary="Transcript, credits and weighted average")
def my_grades(auth=Depends(require_scopes("grades")), db: Session = Depends(get_db)):
    return services.transcript(db, auth[0])
