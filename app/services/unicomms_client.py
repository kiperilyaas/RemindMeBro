"""
UniComms -> Inbox: the lecturers' emails (Outlook) and Teams channel posts.

Read with the shared key (data/unicomms/hub.key) at every Sync and every 30 s by live_sync.py.
- a message to a course becomes a course announcement: every student who follows the course sees it;
- an email to one student becomes a personal message (announcements.user_id), with a personal deadline;
  addressed to an email the hub does not know, it is skipped.
New or edited messages go through the AI (hidden deadlines); a message deleted in UniComms leaves the Inbox.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Announcement, SourceType, User

logger = logging.getLogger(__name__)
PREFIX = "unicomms-"


class UniCommsError(RuntimeError):
    pass


def _key() -> str:
    env = os.getenv("UNICOMMS_HUB_KEY")
    if env:
        return env
    path = Path(settings.UNICOMMS_KEY_FILE)
    if not path.is_file():
        raise UniCommsError("UniComms has not started yet (no key in data/unicomms).")
    return path.read_text().strip()


def fetch() -> List[Dict[str, Any]]:
    try:
        r = httpx.get(f"{settings.UNICOMMS_URL}/api/v1/messages", headers={"X-API-Key": _key()}, timeout=10)
    except httpx.HTTPError as exc:
        raise UniCommsError(f"UniComms is not reachable at {settings.UNICOMMS_URL}") from exc
    if r.status_code != 200:
        raise UniCommsError(f"UniComms answered {r.status_code}")
    return r.json().get("messages", [])


def _content(m: Dict[str, Any]) -> str:
    body = (m.get("body") or "").strip()
    subject = (m.get("subject") or "").strip()
    if not subject or body.lower().startswith(subject.lower()):
        return body
    return f"{subject}{'' if subject[-1] in '.!?' else '.'} {body}"


def sync_messages(db: Session, run_ai: bool = True) -> Dict[str, Any]:
    from app.services import sync_service   # local import: sync_service imports this module

    messages = fetch()
    out: Dict[str, Any] = {"messages": 0, "new": 0, "removed": 0, "ai_details": []}
    seen = set()
    for m in messages:
        ext = f"{PREFIX}{m['id']}"
        owner_id = None
        if m.get("to_email"):
            owner_id = db.scalar(select(User.id).where(func.lower(User.email) == m["to_email"].lower()))
            if owner_id is None:
                continue   # written to someone who has no Remind Me Bro account
        seen.add(ext)
        source = SourceType.EMAIL if m["channel"] == "outlook" else SourceType.TEAMS
        course = sync_service.ensure_course(db, m["course_code"], m.get("course_name"))
        content = _content(m)
        created = datetime.fromisoformat(m["created_at"])
        known = db.scalar(select(Announcement).where(Announcement.source == source, Announcement.external_id == ext))
        if known is None:
            out["new"] += 1
        if run_ai and (known is None or known.content != content):   # the AI reads each message once
            detail = sync_service.process_informal_message(
                db, external_id=ext, content=content, author=m["sender_name"], created_at=created,
                course_code=course.code if course else None, source=source, course_is_certain=course is not None, owner_id=owner_id)
            out["ai_details"].append({**detail, "source": source.value})
        else:
            sync_service.upsert_announcement(db, external_id=ext, source=source, author=m["sender_name"], content=content,
                                             created_at=created, course=course, owner_id=owner_id)
        db.commit()
        out["messages"] += 1
    # deleted in UniComms -> deleted here too (with the deadlines the AI had found in it)
    for ann in list(db.scalars(select(Announcement).where(Announcement.external_id.like(f"{PREFIX}%"),
                                                          Announcement.external_id.not_in(seen)))):
        sync_service.delete_announcement(db, ann)
        out["removed"] += 1
    if out["removed"]:
        db.commit()
    return out
