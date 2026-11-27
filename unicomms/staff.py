"""
UniComms for lecturers: the React app at /staff sends emails (like Outlook) and Teams channel posts
in the name of a lecturer, to every student of a course or to one student.

It works only on the computer that runs the demo (app/api/access.py): there is no password, the lecturer is
picked from the list. State-changing requests must carry `X-Requested-With: staff` (CSRF protection).
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.access import is_local_request
from unicomms import catalog
from unicomms.config import settings
from unicomms.db import get_db
from unicomms.models import Message

router = APIRouter(include_in_schema=False)
STAFF_PAGE = Path(__file__).parent / "static" / "staff" / "index.html"
ONLY_LOCAL = HTTPException(403, "UniComms is only available on the computer that runs the demo.")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _local(request: Request) -> None:
    if not is_local_request(request):
        raise ONLY_LOCAL
    if request.method != "GET" and request.headers.get("x-requested-with") != "staff":
        raise HTTPException(403, "Missing X-Requested-With header.")


@router.get("/", response_class=HTMLResponse)
@router.get("/staff", response_class=HTMLResponse)
@router.get("/staff/", response_class=HTMLResponse)
def staff_page(request: Request):
    if not is_local_request(request):
        return HTMLResponse("<p>UniComms is only available on the computer that runs the demo.</p>", status_code=403)
    if STAFF_PAGE.is_file():
        return FileResponse(STAFF_PAGE, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<p>The UniComms app is not built. Run <code>npm run build</code> in <code>web/</code>.</p>", status_code=503)


def current(request: Request) -> Dict[str, Any]:
    _local(request)
    who = catalog.lecturer(request.session.get("lecturer") or "")
    if who is None:
        raise HTTPException(401, "Pick a lecturer first.")
    return who


def _me(who: Dict[str, Any]) -> Dict[str, Any]:
    return {**who, "role": "Lecturer", "now": settings.now().isoformat(timespec="minutes"),
            "hub_url": os.getenv("RMB_HUB_URL", "http://127.0.0.1:8000/")}


# ---------------------------------------------------------------------------
# "Session": the lecturer picked on this computer
# ---------------------------------------------------------------------------
@router.get("/staff/api/session")
def session(request: Request):
    _local(request)
    who = catalog.lecturer(request.session.get("lecturer") or "")
    return {"user": _me(who) if who else None}


@router.get("/staff/api/demo-accounts")
def demo_accounts(request: Request):
    _local(request)
    accounts = [catalog.lecturer(u) for u, _ in catalog.LECTURERS]
    return {"password": None, "local": True,
            "accounts": [{"id": a["id"], "username": a["username"], "fullname": a["fullname"], "role": "Lecturer"} for a in accounts]}


class QuickBody(BaseModel):
    uid: int


@router.post("/staff/api/quick-login")
def quick_login(body: QuickBody, request: Request):
    _local(request)
    who = catalog.lecturer_by_id(body.uid)
    if who is None:
        raise HTTPException(404, "Unknown lecturer.")
    request.session["lecturer"] = who["username"]
    return _me(who)


@router.post("/staff/api/login")
def login(request: Request):
    _local(request)
    raise HTTPException(400, "UniComms has no passwords: pick a lecturer from the list.")


@router.post("/staff/api/logout")
def logout(request: Request):
    _local(request)
    request.session.pop("lecturer", None)
    return {"ok": True}


@router.get("/staff/api/me")
def me(who: Dict[str, Any] = Depends(current)):
    return _me(who)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
@router.get("/staff/api/catalog")
def course_catalog(who: Dict[str, Any] = Depends(current)):
    return {"courses": catalog.courses_for(who["username"]),
            "students": [{"email": e, "fullname": n} for e, n in catalog.STUDENTS]}


def _out(m: Message, who: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"id": m.id, "channel": m.channel, "sender": m.sender, "sender_name": m.sender_name, "sender_email": m.sender_email,
            "course_code": m.course_code, "course_name": m.course_name, "to_email": m.to_email, "subject": m.subject,
            "body": m.body, "created_at": m.created_at.isoformat(timespec="seconds"), "mine": bool(who and m.sender == who["username"])}


@router.get("/staff/api/messages")
def list_messages(who: Dict[str, Any] = Depends(current), db: Session = Depends(get_db)):
    rows = db.scalars(select(Message).order_by(Message.created_at.desc(), Message.id.desc()).limit(300))
    return [_out(m, who) for m in rows]


class SendBody(BaseModel):
    channel: Literal["outlook", "teams"]
    course_code: str = Field(..., min_length=2, max_length=32)
    course_name: str = Field("", max_length=255)     # only for a course that is not in the list
    to_email: Optional[str] = Field(None, max_length=255)   # empty = every student of the course
    subject: str = Field("", max_length=300)
    body: str = Field(..., min_length=2, max_length=20000)


@router.post("/staff/api/messages", status_code=201)
def send(body: SendBody, who: Dict[str, Any] = Depends(current), db: Session = Depends(get_db)):
    code = body.course_code.strip().upper()
    known = {c: n for c, n, _ in catalog.COURSES}
    name = known.get(code) or body.course_name.strip()
    if not name:
        raise HTTPException(422, "Write the name of the course.")
    to = (body.to_email or "").strip().lower() or None
    if to and not EMAIL_RE.match(to):
        raise HTTPException(422, "The student's email address is not valid.")
    if to and body.channel == "teams":
        raise HTTPException(422, "Teams posts go to the course channel. Write to one student by Outlook.")
    subject = body.subject.strip()
    if body.channel == "outlook" and not subject:
        raise HTTPException(422, "An email needs a subject.")
    m = Message(channel=body.channel, sender=who["username"], sender_name=who["fullname"], sender_email=who["email"],
                course_code=code, course_name=name, to_email=to, subject=subject if body.channel == "outlook" else "",
                body=body.body.strip(), created_at=settings.now().replace(microsecond=0))
    db.add(m)
    db.commit()
    return _out(m, who)


@router.delete("/staff/api/messages/{message_id}")
def delete(message_id: int, request: Request, who: Dict[str, Any] = Depends(current), db: Session = Depends(get_db)):
    m = db.get(Message, message_id)
    if m is None or m.sender != who["username"]:
        raise HTTPException(404, "Message not found.")
    db.delete(m)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# API for the hub (Remind Me Bro): every message, read with the shared key
# ---------------------------------------------------------------------------
@router.get("/api/v1/messages")
def hub_messages(request: Request, db: Session = Depends(get_db)):
    if request.headers.get("x-api-key") != settings.hub_key():
        raise HTTPException(401, "Wrong or missing X-API-Key.")
    rows = db.scalars(select(Message).order_by(Message.created_at, Message.id))
    return {"now": settings.now().isoformat(timespec="seconds"), "messages": [_out(m) for m in rows]}


@router.get("/api/v1/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "time": datetime.now().isoformat(timespec="seconds")}
