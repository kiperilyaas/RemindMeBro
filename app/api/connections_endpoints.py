"""
External connections (UniSIS via OAuth 2.0, UniLearn via Moodle web-service token) and the Studies area.

  POST   /api/connections/moodle                username + password -> UniLearn token (password not stored)
  POST   /api/connections/moodle/sync           import assignments, events and announcements (AI included)
  DELETE /api/connections/moodle                forget the token

  GET    /api/connections                       status of every source
  POST   /api/connections/unisis/start          returns the UniSIS authorize URL (browser goes there)
  GET    /api/connections/unisis/callback       OAuth redirect target (no bearer: identified by `state`)
  POST   /api/connections/unisis/sync           re-import timetable, exams and windows
  DELETE /api/connections/unisis                revoke and remove the connection
  GET    /api/studies                           live data from UniSIS (profile, exams, course registration, grades)
  POST   /api/studies/exams/{id}/registration   register for an exam (written to UniSIS)
  DELETE /api/studies/exams/{id}/registration   cancel it
  POST   /api/studies/courses/{code}/enrollment enroll in an elective / join the waiting list
  DELETE /api/studies/courses/{code}/enrollment drop it
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.database.db import get_db
from app.database.models import User
from app.services import unilearn_client, unisis_client
from app.services.unilearn_client import UniLearnError
from app.services.unisis_client import UniSISError

router = APIRouter(prefix="/api", tags=["Connections & studies"])


def _fail(exc: UniSISError):
    raise HTTPException(status_code=exc.status, detail=str(exc))


def _student(user: User) -> User:
    if user.role.value != "student":
        raise HTTPException(403, "Only students can connect a student information system.")
    return user


@router.get("/connections", summary="Status of the connected systems")
def connections(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> List[Dict[str, Any]]:
    conn = unisis_client.get_connection(db, user)
    unisis = {
        "provider": "unisis",
        "name": "UniSIS",
        "kind": "oauth",
        "portal_url": settings.UNISIS_URL,
        "available": unisis_client.is_available(),
        "status": conn.status if conn else "disconnected",
        "account": conn.external_name if conn else None,
        "account_id": conn.external_id if conn else None,
        "scopes": conn.scope.split() if conn and conn.scope else [],
        "connected_at": conn.connected_at.isoformat() if conn else None,
        "last_sync_at": conn.last_sync_at.isoformat() if conn and conn.last_sync_at else None,
        "last_error": conn.last_error if conn else None,
    }
    ml = unilearn_client.get_connection(db, user)
    unilearn = {
        "provider": "moodle",
        "name": "UniLearn",
        "kind": "token",
        "portal_url": settings.UNILEARN_URL,
        "available": unilearn_client.is_available(),
        "status": ml.status if ml else "disconnected",
        "account": ml.external_name if ml else None,
        "account_id": ml.external_id if ml else None,
        "scopes": [ml.scope] if ml and ml.scope else [],
        "connected_at": ml.connected_at.isoformat() if ml else None,
        "last_sync_at": ml.last_sync_at.isoformat() if ml and ml.last_sync_at else None,
        "last_error": ml.last_error if ml else None,
    }
    demo = [{"provider": p, "name": n, "kind": "demo", "status": "demo"} for p, n in
            (("teams", "Microsoft Teams"), ("email", "University email"))]
    return [unisis, unilearn] + demo


# ---------------------------------------------------------------------------
# UniLearn (Moodle-compatible LMS)
# ---------------------------------------------------------------------------
class MoodleLogin(BaseModel):
    username: str = Field(..., min_length=1, examples=["giulia.esposito"])
    password: str = Field(..., min_length=1, examples=["demo1234"])


def _ul_fail(exc: UniLearnError):
    raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/connections/moodle", summary="Connect UniLearn: exchanges username + password for a web-service token")
def moodle_connect(body: MoodleLogin, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    _student(user)
    try:
        conn = unilearn_client.connect(db, user, body.username, body.password)
        if unisis_client.get_connection(db, user) is not None:
            try:   # courses already chosen in UniSIS: join them in UniLearn too
                unisis_client.mirror_to_unilearn(db, user)
            except UniSISError:
                pass
        result = unilearn_client.sync_user(db, user, run_ai=False)   # fast first import; Sync runs the AI
    except UniLearnError as exc:
        db.rollback()
        _ul_fail(exc)
    result.pop("ai_details", None)
    return {"connected": True, "account": conn.external_name, **result}


@router.post("/connections/moodle/sync", summary="Import assignments, events and announcements from UniLearn")
def moodle_sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        return unilearn_client.sync_user(db, user, run_ai=True)
    except UniLearnError as exc:
        _ul_fail(exc)


@router.delete("/connections/moodle", summary="Disconnect UniLearn (forgets the token)")
def moodle_disconnect(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, bool]:
    return {"disconnected": unilearn_client.disconnect(db, user)}


@router.post("/connections/unisis/start", summary="Start the OAuth 2.0 authorization (returns the URL to open)")
def start(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, str]:
    _student(user)
    if not unisis_client.is_available():
        raise HTTPException(503, f"UniSIS is not running at {settings.UNISIS_URL}.")
    try:
        url = unisis_client.start_authorization(db, user, str(request.base_url))
    except UniSISError as exc:
        _fail(exc)
    return {"authorize_url": url}


@router.get("/connections/unisis/callback", include_in_schema=False)
def callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None,
             error_description: Optional[str] = None, db: Session = Depends(get_db)):
    home = str(request.base_url).rstrip("/") + "/#connections"
    if error:
        msg = "You denied access in UniSIS." if error == "access_denied" else (error_description or error)
        if state:  # discard the pending request
            from app.database.models import OAuthState
            pending = db.get(OAuthState, state)
            if pending:
                db.delete(pending)
                db.commit()
        return RedirectResponse(f"{home}?unisis=error&message={quote(msg)}", status_code=303)
    if not code or not state:
        return RedirectResponse(f"{home}?unisis=error&message={quote('Missing code or state.')}", status_code=303)
    try:
        conn = unisis_client.complete_authorization(db, state, code)
        user = db.get(User, conn.user_id)
        try:
            unisis_client.sync_user(db, user)
        except UniSISError:
            pass  # the connection is valid; the user can sync again
    except UniSISError as exc:
        return RedirectResponse(f"{home}?unisis=error&message={quote(str(exc))}", status_code=303)
    return RedirectResponse(f"{home}?unisis=connected", status_code=303)


@router.post("/connections/unisis/sync", summary="Import timetable, exam dates and registration windows")
def sync(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    try:
        return unisis_client.sync_user(db, user)
    except UniSISError as exc:
        _fail(exc)


@router.delete("/connections/unisis", summary="Disconnect UniSIS (revokes the tokens)")
def disconnect(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, bool]:
    return {"disconnected": unisis_client.disconnect(db, user)}


@router.get("/studies", summary="Live data from UniSIS for the Studies page")
def studies(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    conn = unisis_client.get_connection(db, user)
    if conn is None or conn.status != "connected":
        return {"connected": False, "status": conn.status if conn else "disconnected", "portal_url": settings.UNISIS_URL}
    try:
        data = unisis_client.studies(db, user)
    except UniSISError as exc:
        db.refresh(conn)
        if conn.status != "connected":  # access revoked in UniSIS: report it, don't fail
            return {"connected": False, "status": conn.status, "portal_url": settings.UNISIS_URL, "error": conn.last_error}
        _fail(exc)
    return {"connected": True, "portal_url": settings.UNISIS_URL, "last_sync_at": conn.last_sync_at.isoformat() if conn.last_sync_at else None, **data}


def _write(db: Session, user: User, method: str, path: str) -> Dict[str, Any]:
    try:
        result = unisis_client.call(db, user, method, path)
        unisis_client.sync_user(db, user)  # refresh deadlines and timetable right away (and follow the change in UniLearn)
        ul = unilearn_client.get_connection(db, user)
        if ul is not None and ul.status == "connected":
            try:   # bring in (or drop) the course's assignments and events now, without waiting for Sync
                unilearn_client.sync_user(db, user, run_ai=False).pop("ai_details", None)
            except UniLearnError:
                pass
        return result
    except UniSISError as exc:
        _fail(exc)


@router.post("/studies/exams/{exam_id}/registration", summary="Register for an exam in UniSIS")
def register_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _write(db, user, "POST", f"/api/v1/me/exams/{exam_id}/registration")


@router.delete("/studies/exams/{exam_id}/registration", summary="Cancel an exam registration in UniSIS")
def cancel_exam(exam_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _write(db, user, "DELETE", f"/api/v1/me/exams/{exam_id}/registration")


@router.post("/studies/courses/{course_code}/enrollment", summary="Enroll in a course / join the waiting list in UniSIS")
def enroll(course_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _write(db, user, "POST", f"/api/v1/me/course-registration/{course_code}")


@router.delete("/studies/courses/{course_code}/enrollment", summary="Drop a course in UniSIS")
def drop(course_code: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _write(db, user, "DELETE", f"/api/v1/me/course-registration/{course_code}")
