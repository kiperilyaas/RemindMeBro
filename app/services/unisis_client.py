"""
UniSIS connector — the hub acts as an OAuth 2.0 confidential client.

Flow: start_authorization() -> student consents on UniSIS -> complete_authorization()
exchanges the code (client secret + PKCE) for tokens, stored encrypted. Every API
call refreshes the access token when needed. sync_user() turns UniSIS data into
personal timetable events and deadlines (registration windows) inside the hub.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Connection, Course, Deadline, Event, OAuthState, SourceType, User
from app.services.sync_lock import exclusive

logger = logging.getLogger(__name__)
PROVIDER = "unisis"
CALLBACK_PATH = "/api/connections/unisis/callback"


class UniSISError(Exception):
    """Generic connector error (shown to the user)."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class NotConnected(UniSISError):
    def __init__(self, message: str = "UniSIS is not connected. Connect it from the Connections page."):
        super().__init__(message, 409)


# ---------------------------------------------------------------------------
# Credentials and token encryption
# ---------------------------------------------------------------------------
def credentials() -> Dict[str, str]:
    """Client credentials: env vars first, then the file exported by UniSIS ("downloaded credentials")."""
    creds = {"client_id": settings.UNISIS_CLIENT_ID, "client_secret": settings.UNISIS_CLIENT_SECRET, "api_key": settings.UNISIS_API_KEY}
    if not creds["client_secret"]:
        try:
            with open(settings.UNISIS_CREDENTIALS_FILE) as fh:
                data = json.load(fh)
            creds["client_id"] = data.get("client_id", creds["client_id"])
            creds["client_secret"] = data.get("client_secret", "")
            creds["api_key"] = creds["api_key"] or data.get("api_key", "")
        except (OSError, ValueError):
            pass
    if not creds["client_secret"]:
        raise UniSISError("UniSIS client credentials not found. Start UniSIS once (it exports them) or set UNISIS_CLIENT_SECRET.", 503)
    return creds


def _fernet() -> Fernet:
    key = hashlib.sha256((settings.jwt_secret() + ":connections").encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None


def get_connection(db: Session, user: User) -> Optional[Connection]:
    return db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == PROVIDER))


def _http() -> httpx.Client:
    return httpx.Client(base_url=settings.UNISIS_URL, timeout=15.0)


def is_available() -> bool:
    try:
        with _http() as c:
            return c.get("/.well-known/oauth-authorization-server", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


# ---------------------------------------------------------------------------
# Authorization Code + PKCE
# ---------------------------------------------------------------------------
def start_authorization(db: Session, user: User, hub_base_url: str) -> str:
    creds = credentials()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    redirect_uri = hub_base_url.rstrip("/") + CALLBACK_PATH
    # Clean up abandoned attempts
    for old in db.scalars(select(OAuthState).where(OAuthState.created_at < datetime.now() - timedelta(minutes=30))):
        db.delete(old)
    db.add(OAuthState(state=state, user_id=user.id, provider=PROVIDER, code_verifier=verifier, redirect_uri=redirect_uri))
    db.commit()
    query = urlencode({
        "response_type": "code",
        "client_id": creds["client_id"],
        "redirect_uri": redirect_uri,
        "scope": settings.UNISIS_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return f"{settings.UNISIS_URL}/oauth/authorize?{query}"


def _store_tokens(conn: Connection, payload: Dict[str, Any]) -> None:
    conn.access_token_enc = encrypt(payload["access_token"])
    if payload.get("refresh_token"):
        conn.refresh_token_enc = encrypt(payload["refresh_token"])
    conn.expires_at = datetime.now() + timedelta(seconds=int(payload.get("expires_in", 3600)) - 30)
    conn.scope = payload.get("scope", conn.scope or "")
    conn.status = "connected"
    conn.last_error = None


def complete_authorization(db: Session, state: str, code: str) -> Connection:
    pending = db.get(OAuthState, state)
    if pending is None or pending.created_at < datetime.now() - timedelta(minutes=30):
        raise UniSISError("The connection request expired. Please try again.", 400)
    user_id, verifier, redirect_uri = pending.user_id, pending.code_verifier, pending.redirect_uri
    db.delete(pending)
    db.commit()
    creds = credentials()
    try:
        with _http() as c:
            r = c.post("/oauth/token", data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri, "code_verifier": verifier,
            }, auth=(creds["client_id"], creds["client_secret"]))
    except httpx.HTTPError as exc:
        raise UniSISError(f"UniSIS is not reachable: {exc}", 503)
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        raise UniSISError(f"Token exchange failed: {body.get('error_description') or r.text}", 400)
    payload = r.json()
    conn = db.scalar(select(Connection).where(Connection.user_id == user_id, Connection.provider == PROVIDER))
    if conn is None:
        conn = Connection(user_id=user_id, provider=PROVIDER, access_token_enc="", expires_at=datetime.now())
        db.add(conn)
    _store_tokens(conn, payload)
    conn.external_id = payload.get("student_number")
    conn.external_name = payload.get("full_name")
    conn.connected_at = datetime.now()
    db.commit()
    return conn


def provision_student(db: Session, user: User, password: str) -> Connection:
    """Signs the student up in UniSIS (same email and password) and stores the tokens UniSIS returns: connected at once."""
    creds = credentials()
    try:
        with _http() as c:
            r = c.post("/api/v1/provisioning/students", json={"email": user.email, "full_name": user.full_name, "password": password},
                       auth=(creds["client_id"], creds["client_secret"]))
    except httpx.HTTPError as exc:
        raise UniSISError(f"UniSIS is not reachable: {exc}", 503)
    if r.status_code != 200:
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        raise UniSISError(body.get("error_description") or f"UniSIS sign-up failed ({r.status_code}).", r.status_code)
    payload = r.json()
    conn = get_connection(db, user)
    if conn is None:
        conn = Connection(user_id=user.id, provider=PROVIDER, access_token_enc="", expires_at=datetime.now())
        db.add(conn)
    _store_tokens(conn, payload)
    conn.external_id = payload.get("student_number")
    conn.external_name = payload.get("full_name")
    conn.connected_at = datetime.now()
    db.commit()
    return conn


def _refresh(db: Session, conn: Connection) -> None:
    refresh_token = decrypt(conn.refresh_token_enc)
    if not refresh_token:
        raise _expire(db, conn, "No refresh token available.")
    creds = credentials()
    try:
        with _http() as c:
            r = c.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh_token},
                       auth=(creds["client_id"], creds["client_secret"]))
    except httpx.HTTPError as exc:
        raise UniSISError(f"UniSIS is not reachable: {exc}", 503)
    if r.status_code != 200:
        raise _expire(db, conn, "UniSIS refused the refresh token (access revoked?).")
    _store_tokens(conn, r.json())
    db.commit()


def _expire(db: Session, conn: Connection, reason: str) -> UniSISError:
    conn.status = "expired"
    conn.last_error = reason
    db.commit()
    # 409 (not 401): the hub session is still valid, only the UniSIS link is gone
    return UniSISError("Access to UniSIS was revoked or expired. Connect UniSIS again.", 409)


def call(db: Session, user: User, method: str, path: str, **kwargs) -> Any:
    """Authenticated API call with automatic token refresh and error mapping."""
    conn = get_connection(db, user)
    if conn is None or conn.status != "connected":
        raise NotConnected()
    if conn.expires_at <= datetime.now():
        _refresh(db, conn)
    for attempt in (1, 2):
        token = decrypt(conn.access_token_enc)
        try:
            with _http() as c:
                r = c.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
        except httpx.HTTPError as exc:
            raise UniSISError(f"UniSIS is not reachable at {settings.UNISIS_URL}: {exc.__class__.__name__}", 503)
        if r.status_code == 401 and attempt == 1:
            _refresh(db, conn)
            continue
        if r.status_code == 401:
            raise _expire(db, conn, "Access token rejected.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail") or r.text
            except ValueError:
                detail = r.text
            raise UniSISError(str(detail), r.status_code if r.status_code in (403, 404, 409, 422) else 502)
        return r.json()
    raise UniSISError("Unexpected UniSIS error.")


def disconnect(db: Session, user: User) -> bool:
    conn = get_connection(db, user)
    if conn is None:
        return False
    token = decrypt(conn.refresh_token_enc) or decrypt(conn.access_token_enc)
    if token:
        try:
            creds = credentials()
            with _http() as c:
                c.post("/oauth/revoke", data={"token": token}, auth=(creds["client_id"], creds["client_secret"]), timeout=5)
        except (httpx.HTTPError, UniSISError):
            logger.warning("Could not revoke the UniSIS token remotely (removed locally anyway)")
    _remove_personal_data(db, user)
    db.delete(conn)
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def studies(db: Session, user: User) -> Dict[str, Any]:
    """Live view for the Studies page."""
    return {
        "profile": call(db, user, "GET", "/api/v1/me"),
        "enrollments": call(db, user, "GET", "/api/v1/me/enrollments"),
        "exams": call(db, user, "GET", "/api/v1/me/exams"),
        "course_registration": call(db, user, "GET", "/api/v1/me/course-registration"),
        "grades": call(db, user, "GET", "/api/v1/me/grades"),
    }


def _remove_personal_data(db: Session, user: User) -> None:
    for d in db.scalars(select(Deadline).where(Deadline.user_id == user.id, Deadline.source == SourceType.UNISIS)):
        db.delete(d)
    for e in db.scalars(select(Event).where(Event.user_id == user.id, Event.source == PROVIDER)):
        db.delete(e)


def _course(db: Session, code: Optional[str], name: Optional[str] = None) -> Optional[Course]:
    """Hub course for a UniSIS code; created when UniSIS knows the course and the hub does not yet."""
    from app.services import sync_service   # local import: sync_service imports this module
    return sync_service.ensure_course(db, code, name)


def _upsert_deadline(db: Session, user: User, key: str, title: str, due: datetime, description: str, course_code: Optional[str]) -> str:
    ext = f"unisis:{user.id}:{key}"
    d = db.scalar(select(Deadline).where(Deadline.source == SourceType.UNISIS, Deadline.external_id == ext))
    if d is None:
        d = Deadline(source=SourceType.UNISIS, external_id=ext, user_id=user.id, is_completed=False, extracted_by_ai=False)
        db.add(d)
    course = _course(db, course_code)
    d.course_id = course.id if course else None
    d.title, d.due_date, d.description = title, due, description
    return ext


def _fmt(dt: datetime) -> str:
    return dt.strftime("%a %d %b, %H:%M")


def mirror_to_unilearn(db: Session, user: User, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Courses chosen in UniSIS -> the same courses in UniLearn (only when UniLearn is connected)."""
    from app.services import unilearn_client   # local import: unilearn_client imports sync_service which imports this module
    if data is None:
        data = {"enrollments": call(db, user, "GET", "/api/v1/me/enrollments"),
                "course_registration": call(db, user, "GET", "/api/v1/me/course-registration")}
    enrolled = {e["course_code"] for e in data["enrollments"] if e["status"] == "enrolled"}
    known = {e["course_code"] for e in data["enrollments"]} | {o["course_code"] for o in ((data.get("course_registration") or {}).get("offers") or [])}
    try:
        return unilearn_client.mirror_enrolments(db, user, enrolled, known)
    except unilearn_client.UniLearnError as exc:
        return {"error": str(exc)}


@exclusive
def sync_user(db: Session, user: User) -> Dict[str, Any]:
    """Imports timetable, exam dates and registration windows as personal events and deadlines."""
    conn = get_connection(db, user)
    if conn is None or conn.status != "connected":
        raise NotConnected()
    today = settings.reference_now().date()
    start = today - timedelta(days=today.weekday() + 7)
    end = start + timedelta(days=150)
    data = studies(db, user)
    timetable = call(db, user, "GET", "/api/v1/me/timetable", params={"from": start.isoformat(), "to": end.isoformat()})

    # --- timetable + registered exams -> personal events ---
    seen_events = set()
    for item in timetable:
        ext = f"unisis:{user.id}:{item['id']}"
        seen_events.add(ext)
        ev = db.scalar(select(Event).where(Event.external_id == ext))
        if ev is None:
            ev = Event(external_id=ext, user_id=user.id, source=PROVIDER)
            db.add(ev)
        course = _course(db, item["course_code"], item.get("course_name") or (item["title"] if item["type"] == "class" else None))
        ev.course_id = course.id if course else None
        ev.title = item["title"] if item["type"] == "class" else f"Exam: {item['title']}"
        ev.kind = item["type"]
        ev.start_time = datetime.fromisoformat(item["start"])
        ev.end_time = datetime.fromisoformat(item["end"])
        ev.location = item["room"]
    for ev in db.scalars(select(Event).where(Event.user_id == user.id, Event.source == PROVIDER)):
        if ev.external_id not in seen_events:
            db.delete(ev)

    # --- registration windows -> personal deadlines ---
    seen = set()
    exams = data["exams"]
    finals_by_course: Dict[str, List[Dict[str, Any]]] = {}
    for e in exams:
        if not e["is_partial"]:
            finals_by_course.setdefault(e["course_code"], []).append(e)
    # Final exams still to book, grouped by registration window (one reminder per window, not per course)
    pending_by_window: Dict[str, List[Dict[str, Any]]] = {}
    for code, terms in finals_by_course.items():
        if any(t["registered"] for t in terms) or any(t["reason"] == "Already passed" for t in terms):
            continue
        candidates = [t for t in terms if t["registration_status"] in ("open", "upcoming")]
        if candidates:
            first = min(candidates, key=lambda t: t["registration_closes_at"])
            pending_by_window.setdefault(first["registration_closes_at"], []).append(first)
    for closes, group in pending_by_window.items():
        first = group[0]
        opens = datetime.fromisoformat(first["registration_opens_at"])
        when = "is open now" if first["registration_status"] == "open" else f"opens {_fmt(opens)}"
        names = ", ".join(sorted(t["course_name"] for t in group))
        title = f"Register for the {first['course_name']} exam" if len(group) == 1 else f"Register for {len(group)} exams (winter session)"
        seen.add(_upsert_deadline(
            db, user, f"exam-reg:{closes}", title, datetime.fromisoformat(closes),
            f"UniSIS exam registration {when}: {names}.", first["course_code"] if len(group) == 1 else None))
    for e in exams:
        if not e["is_partial"] or e["registered"]:
            continue
        if e["registration_status"] == "upcoming" or (e["registration_status"] == "open" and e["can_register"]):
            seats = f"{e['seats_left']} seat(s) left" if e["registration_status"] == "open" else f"opens {_fmt(datetime.fromisoformat(e['registration_opens_at']))}"
            seen.add(_upsert_deadline(
                db, user, f"partial-reg:{e['id']}", f"Register for the {e['course_name']} {e['title'][:1].lower() + e['title'][1:]}",
                datetime.fromisoformat(e["registration_closes_at"]),
                f"UniSIS registration · {seats}. Test on {_fmt(datetime.fromisoformat(e['starts_at']))}.", e["course_code"]))
    reg = data["course_registration"]
    if reg and reg["status"] in ("open", "upcoming") and reg["electives_chosen"] < reg["electives_required"]:
        missing = reg["electives_required"] - reg["electives_chosen"]
        seen.add(_upsert_deadline(
            db, user, f"course-reg:{reg['term']['code']}", f"Choose {missing} elective(s) for the {reg['term']['name']}",
            datetime.fromisoformat(reg["closes_at"]),
            f"UniSIS course registration is {reg['status']}. Popular electives fill up fast.", None))
    for d in db.scalars(select(Deadline).where(Deadline.user_id == user.id, Deadline.source == SourceType.UNISIS)):
        if d.external_id not in seen:
            db.delete(d)

    # --- snapshot for the AI assistant ---
    prof = data["profile"]
    conn.snapshot = json.dumps({
        "course_codes": sorted(e["course_code"] for e in data["enrollments"] if e["status"] == "enrolled"),   # courses the student follows
        "programme": f"{prof['programme']['degree']} {prof['programme']['name']}" if prof.get("programme") else None,
        "year": prof.get("year_of_study"),
        "credits_earned": prof["credits"]["earned"],
        "credits_required": prof["credits"]["required"],
        "credits_in_progress": prof["credits"]["in_progress"],
        "weighted_average": prof.get("weighted_average"),
        "registered_exams": [f"{e['course_name']} · {e['title']} on {_fmt(datetime.fromisoformat(e['starts_at']))}" for e in exams if e["registered"]],
        "exam_registration": [
            f"{e['course_name']} · {e['title']} ({_fmt(datetime.fromisoformat(e['starts_at']))}): registration {e['registration_status']}"
            f"{', ' + str(e['seats_left']) + ' seats left' if e['registration_status'] == 'open' else ''}"
            for e in exams if not e["registered"]
        ][:12],
        "electives": {
            "term": reg["term"]["name"], "status": reg["status"], "required": reg["electives_required"],
            "chosen": [o["course_name"] for o in reg["offers"] if o["status"] == "enrolled"],
            "waitlisted": [o["course_name"] for o in reg["offers"] if o["status"] == "waitlisted"],
        } if reg else None,
        "recent_grades": [f"{g['course_name']}: {g['grade']}" + (f" ({g['grade_name']})" if g.get("grade_name") and g.get("grade_value") else "")
                          for g in data["grades"]["records"][-5:]],
    })
    conn.last_sync_at = datetime.now()
    conn.last_error = None
    db.commit()
    unilearn = mirror_to_unilearn(db, user, data)   # the courses chosen here are the ones the student follows in UniLearn
    return {
        "status": "ok",
        "events": len(seen_events),
        "deadlines": len(seen),
        "student": conn.external_name,
        "unilearn": unilearn,
    }
