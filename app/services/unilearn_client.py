"""
UniLearn connector — talks to UniLearn through the standard Moodle web-service API,
exactly like the Moodle mobile app does. Pointing UNILEARN_URL at a real Moodle site
(with mobile web services enabled) works the same way.

  connect():  login/token.php (username + password, service=moodle_mobile_app) -> token
              The password is used once and never stored; the token is stored encrypted.
  sync_user(): core_enrol_get_users_courses, mod_assign_get_assignments,
              mod_assign_get_submission_status, core_calendar_get_calendar_events,
              mod_forum_get_forums_by_courses, mod_forum_get_forum_discussions
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Announcement, Connection, Course, Deadline, DeadlineDone, Event, SourceType, User
from app.services.unisis_client import decrypt, encrypt

logger = logging.getLogger(__name__)
PROVIDER = "moodle"
SERVICE = "moodle_mobile_app"


class UniLearnError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def get_connection(db: Session, user: User) -> Optional[Connection]:
    return db.scalar(select(Connection).where(Connection.user_id == user.id, Connection.provider == PROVIDER))


def _http() -> httpx.Client:
    return httpx.Client(base_url=settings.UNILEARN_URL, timeout=20.0, headers={"X-Client-Name": "Remind Me Bro"})


def is_available() -> bool:
    try:
        with _http() as c:
            return c.get("/login", timeout=3).status_code < 500
    except httpx.HTTPError:
        return False


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip().replace("  ", " ")


def _flatten(params: Dict[str, Any]) -> Dict[str, Any]:
    """{'courseids': [1, 2]} -> {'courseids[0]': 1, 'courseids[1]': 2}  (Moodle array syntax)."""
    out: Dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                out[f"{key}[{i}]"] = v
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------
def connect(db: Session, user: User, username: str, password: str) -> Connection:
    try:
        with _http() as c:
            r = c.post("/login/token.php", data={"username": username, "password": password, "service": SERVICE})
    except httpx.HTTPError:
        raise UniLearnError(f"UniLearn is not reachable at {settings.UNILEARN_URL}.", 503)
    data = r.json()
    if "token" not in data:
        raise UniLearnError(data.get("error") or "Login failed.", 400)
    conn = get_connection(db, user)
    if conn is None:
        conn = Connection(user_id=user.id, provider=PROVIDER, access_token_enc="", expires_at=datetime.now())
        db.add(conn)
    conn.access_token_enc = encrypt(data["token"])
    conn.refresh_token_enc = None
    conn.expires_at = datetime.now() + timedelta(days=3650)   # Moodle tokens do not expire by default
    conn.scope = SERVICE
    conn.status = "connected"
    conn.last_error = None
    conn.connected_at = datetime.now()
    db.commit()
    info = call(db, user, "core_webservice_get_site_info")
    conn.external_id = info.get("username")
    conn.external_name = info.get("fullname")
    db.commit()
    return conn


def mirror_enrolments(db: Session, user: User, enrolled: set, known: set) -> Dict[str, List[str]]:
    """
    UniSIS is where the student chooses courses; UniLearn follows it, like a university LMS fed by its SIS.
    enrolled = course codes the student takes in UniSIS; known = every UniSIS code we saw (taken, waiting list or offered).
    Joins the UniLearn courses with those codes (self-enrolment) and leaves the ones dropped in UniSIS.
    Courses that exist only in UniLearn are never touched.
    """
    conn = get_connection(db, user)
    if conn is None or conn.status != "connected":
        return {"joined": [], "left": []}
    info = call(db, user, "core_webservice_get_site_info")
    mine = {c["shortname"].upper(): c["id"] for c in call(db, user, "core_enrol_get_users_courses", userid=info["userid"])
            if c.get("role", "student") == "student"}
    catalogue = {c["shortname"].upper(): c["id"] for c in call(db, user, "core_course_get_courses_by_field").get("courses", [])}
    enrolled, known = {c.upper() for c in enrolled}, {c.upper() for c in known}
    joined = [code for code in sorted(enrolled - set(mine)) if code in catalogue]
    left = [code for code in sorted(set(mine) & (known - enrolled))]
    for code in joined:
        call(db, user, "enrol_self_enrol_user", courseid=catalogue[code])
    for code in left:
        call(db, user, "local_unilearn_self_unenrol", courseid=mine[code])
    return {"joined": joined, "left": left}


def _provisioning_key() -> str:
    import os
    from app.config import DATA_DIR
    key = os.getenv("UNILEARN_PROVISIONING_KEY", "")
    path = DATA_DIR / "unilearn" / "provisioning.key"
    if not key and path.exists():
        key = path.read_text().strip()
    return key


def provision_student(email: str, firstname: str, lastname: str, password: str) -> None:
    """Creates the student's UniLearn account (username = email). An existing account with that email is fine."""
    key = _provisioning_key()
    if not key:
        raise UniLearnError("UniLearn's provisioning key was not found (start UniLearn once).", 503)
    try:
        with _http() as c:
            r = c.post("/admin/tool/provision/student", headers={"X-Provisioning-Key": key},
                       json={"email": email, "firstname": firstname, "lastname": lastname, "password": password})
    except httpx.HTTPError:
        raise UniLearnError(f"UniLearn is not reachable at {settings.UNILEARN_URL}.", 503)
    if r.status_code not in (200, 409):
        raise UniLearnError(f"UniLearn sign-up failed ({r.status_code}).", r.status_code)


def call(db: Session, user: User, function: str, **params) -> Any:
    conn = get_connection(db, user)
    if conn is None or conn.status != "connected":
        raise UniLearnError("UniLearn is not connected. Connect it from the Connections page.", 409)
    payload = {"wstoken": decrypt(conn.access_token_enc), "wsfunction": function, "moodlewsrestformat": "json", **_flatten(params)}
    try:
        with _http() as c:
            r = c.post("/webservice/rest/server.php", data=payload)
    except httpx.HTTPError:
        raise UniLearnError(f"UniLearn is not reachable at {settings.UNILEARN_URL}.", 503)
    data = r.json()
    if isinstance(data, dict) and data.get("exception"):
        if data.get("errorcode") in {"invalidtoken", "accessexception"}:
            conn.status = "expired"
            conn.last_error = data.get("message")
            db.commit()
            raise UniLearnError("The UniLearn token was deleted or is no longer valid. Connect UniLearn again.", 409)
        raise UniLearnError(f"{function}: {data.get('message')}", 502)
    return data


def disconnect(db: Session, user: User) -> bool:
    conn = get_connection(db, user)
    if conn is None:
        return False
    db.delete(conn)   # Moodle has no token-revocation web service: the student can delete it under Security keys
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
def _course(db: Session, shortname: str) -> Optional[Course]:
    return db.scalar(select(Course).where(Course.code == shortname))


def sync_user(db: Session, user: User, run_ai: bool = True) -> Dict[str, Any]:
    """
    Imports assignments (deadlines + submission status), course events and announcement-forum
    posts. Course data is shared in the hub (user_id = None), like course data in Moodle.
    Forum posts go through the same AI pipeline as Teams messages (run_ai=True).
    """
    from app.services import sync_service  # local import: sync_service imports this module

    info = call(db, user, "core_webservice_get_site_info")
    courses = call(db, user, "core_enrol_get_users_courses", userid=info["userid"])
    by_id = {c["id"]: c for c in courses}
    for c in courses:   # courses created in UniLearn appear in the hub too (same code = same course)
        sync_service.ensure_course(db, c["shortname"], c.get("fullname") or c["shortname"])
    course_ids = list(by_id)
    result: Dict[str, Any] = {"status": "ok", "courses": len(courses), "assignments": 0, "submitted": 0, "events": 0, "posts": 0, "ai_details": []}

    # --- assignments -> deadlines ---
    assignments = call(db, user, "mod_assign_get_assignments", courseids=course_ids)
    seen = set()
    for c in assignments.get("courses", []):
        hub_course = _course(db, c["shortname"])
        for a in c["assignments"]:
            ext = f"unilearn-assign-{a['id']}"
            seen.add(ext)
            due = datetime.fromtimestamp(a["duedate"])
            d = db.scalar(select(Deadline).where(Deadline.source == SourceType.MOODLE, Deadline.external_id == ext))
            if d is None:
                d = Deadline(source=SourceType.MOODLE, external_id=ext, is_completed=False, extracted_by_ai=False)
                db.add(d)
            elif d.due_date != due and d.superseded_by_id:
                # The lecturer changed the official date in the LMS: it is authoritative again,
                # the date the AI found in a message is now the outdated one.
                newer = db.get(Deadline, d.superseded_by_id)
                d.superseded_by_id = None
                if newer is not None and newer.extracted_by_ai:
                    newer.superseded_by_id = d.id
            d.course_id = hub_course.id if hub_course else None
            d.title = a["name"]
            d.description = _strip_html(a.get("intro", ""))
            d.due_date = due
            d.source_updated_at = datetime.fromtimestamp(a["timemodified"]) if a.get("timemodified") else None
            status = call(db, user, "mod_assign_get_submission_status", assignid=a["id"])
            submitted = status.get("lastattempt", {}).get("submission", {}).get("status") == "submitted"
            if submitted:   # a submission in the LMS ticks the deadline off for this student (a manual tick is kept)
                db.flush()
                if not db.scalar(select(DeadlineDone).where(DeadlineDone.user_id == user.id, DeadlineDone.deadline_id == d.id)):
                    db.add(DeadlineDone(user_id=user.id, deadline_id=d.id))
            result["assignments"] += 1
            result["submitted"] += int(submitted)
    # remove assignments deleted in UniLearn, only inside this student's courses (other students' courses are not ours to judge)
    my_course_ids = [c.id for c in db.scalars(select(Course).where(Course.code.in_([c["shortname"] for c in courses])))]
    for d in db.scalars(select(Deadline).where(Deadline.source == SourceType.MOODLE, Deadline.external_id.like("unilearn-assign-%"),
                                               Deadline.course_id.in_(my_course_ids))):
        if d.external_id not in seen:
            for done in db.scalars(select(DeadlineDone).where(DeadlineDone.deadline_id == d.id)):
                db.delete(done)
            db.delete(d)

    # --- course events (assignment due events are already deadlines) ---
    events = call(db, user, "core_calendar_get_calendar_events", **{"events[courseids]": course_ids})
    seen_ev = set()
    for e in events.get("events", []):
        if e.get("eventtype") != "course":
            continue
        ext = f"unilearn-event-{e['id']}"
        seen_ev.add(ext)
        ev = db.scalar(select(Event).where(Event.external_id == ext))
        if ev is None:
            ev = Event(external_id=ext, source="moodle", kind="event")
            db.add(ev)
        c = by_id.get(e["courseid"])
        hub_course = _course(db, c["shortname"]) if c else None
        ev.course_id = hub_course.id if hub_course else None
        ev.title = e["name"]
        ev.start_time = datetime.fromtimestamp(e["timestart"])
        ev.end_time = ev.start_time + timedelta(seconds=e.get("timeduration") or 3600)
        ev.location = e.get("location") or None
        result["events"] += 1
    for ev in db.scalars(select(Event).where(Event.external_id.like("unilearn-event-%"), Event.course_id.in_(my_course_ids))):
        if ev.external_id not in seen_ev:
            db.delete(ev)
    db.commit()

    # --- announcement forums -> announcements (+ AI deadline extraction) ---
    forums = call(db, user, "mod_forum_get_forums_by_courses", courseids=course_ids)
    for f in forums:
        if f.get("type") != "news":
            continue
        shortname = by_id.get(f["course"], {}).get("shortname")
        for d in call(db, user, "mod_forum_get_forum_discussions", forumid=f["id"]).get("discussions", []):
            text = _strip_html(d.get("message", ""))
            subject = d.get("subject") or ""
            content = text if text.lower().startswith(subject.lower()) else f"{subject}. {text}"
            kwargs = dict(external_id=f"unilearn-post-{d['id']}", content=content, author=d.get("userfullname") or "Lecturer",
                          created_at=datetime.fromtimestamp(d["created"]), course_code=shortname, source=SourceType.MOODLE)
            known = db.scalar(select(Announcement).where(Announcement.source == SourceType.MOODLE,
                                                         Announcement.external_id == kwargs["external_id"]))
            if run_ai and (known is None or known.content != content):   # the AI reads each post once
                result["ai_details"].append(sync_service.process_informal_message(db, **kwargs))
            else:
                sync_service.upsert_announcement(db, external_id=kwargs["external_id"], source=SourceType.MOODLE, author=kwargs["author"],
                                                 content=content, created_at=kwargs["created_at"], course=_course(db, shortname) if shortname else None)
            db.commit()
            result["posts"] += 1

    conn = get_connection(db, user)
    conn.snapshot = json.dumps({"course_codes": sorted(c["shortname"] for c in courses if c.get("role", "student") == "student")})
    conn.last_sync_at = datetime.now()
    conn.last_error = None
    db.commit()
    return result
