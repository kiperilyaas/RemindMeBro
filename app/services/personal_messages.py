"""
Outlook and Teams messages that a student adds to the Inbox by hand.

A real Outlook/Teams connection (Microsoft Graph) needs an app registered in Azure and the university's
admin consent, so the demo takes the messages from the student: pasted text, or an email saved from Outlook
as .eml. They go through the same pipeline as the lecturers' announcements (SQLite + ChromaDB + llama3.2
looking for a deadline), but they are personal: only their owner sees the message and the deadline found in it,
and they never move the course deadlines that the other students see.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import SourceType, User
from app.services import sync_service


class EmlError(ValueError):
    pass


def _html_to_text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", raw)
    raw = re.sub(r"(?i)</?(b|i|u|em|strong|span|a|font|small|sup|sub)\b[^>]*>", "", raw)   # inline tags: no extra space
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return _tidy(text)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_eml(raw: bytes) -> Dict[str, Any]:
    """An email saved from Outlook (.eml) -> sender, subject, date and plain text."""
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as exc:  # malformed file
        raise EmlError("This file is not an email (.eml).") from exc
    if not (msg.get("From") or msg.get("Subject")):
        raise EmlError("This file is not an email (.eml). In Outlook: open the email → … → Download (or Save as).")
    body = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            content = body.get_content()
        except Exception:  # unknown charset: keep what can be read
            content = (body.get_payload(decode=True) or b"").decode("utf-8", "replace")
        text = _html_to_text(content) if body.get_content_type() == "text/html" else _tidy(content)
    author = ""
    senders = getaddresses([str(msg.get("From", ""))])
    if senders:
        name, addr = senders[0]
        author = name or addr
    sent_at: Optional[datetime] = None
    if msg.get("Date"):
        try:
            sent_at = parsedate_to_datetime(str(msg["Date"]))
            if sent_at.tzinfo is not None:
                sent_at = sent_at.astimezone().replace(tzinfo=None)   # the app works in local time
        except (TypeError, ValueError):
            sent_at = None
    return {"author": author.strip(), "subject": str(msg.get("Subject", "") or "").strip(), "content": text, "sent_at": sent_at}


def add_message(db: Session, user: User, *, source: SourceType, author: str, content: str, subject: str = "",
                course_code: Optional[str] = None, sent_at: Optional[datetime] = None) -> Dict[str, Any]:
    """Saves the message for this student only and lets the AI look for a deadline in it."""
    content = _tidy(content)
    subject = subject.strip()
    if subject and not content.lower().startswith(subject.lower()):
        content = f"{subject}{'' if subject[-1] in '.!?' else '.'} {content}"
    detail = sync_service.process_informal_message(
        db,
        external_id=f"{'outlook' if source == SourceType.EMAIL else 'teams'}-{uuid.uuid4().hex[:12]}",
        content=content,
        author=author.strip() or ("Outlook" if source == SourceType.EMAIL else "Teams"),
        created_at=sent_at or settings.reference_now(),
        course_code=course_code or None,
        source=source,
        course_is_certain=bool(course_code),
        owner_id=user.id,
    )
    db.commit()
    return detail
