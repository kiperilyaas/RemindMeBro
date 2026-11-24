"""
Moodle-compatible web services.

  /login/token.php               username + password + service  ->  {"token": "..."}
  /webservice/rest/server.php    wstoken + wsfunction + moodlewsrestformat=json (+ function parameters)

Same request/response shapes as Moodle (subset), including Moodle's error format
(HTTP 200 with {"exception", "errorcode", "message"}) and its array parameter
syntax (courseids[0]=1&courseids[1]=2). A client written for Moodle works here.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from unilearn.config import settings
from unilearn.db import get_db
from unilearn.models import Assignment, CalendarEvent, Course, Discussion, Enrolment, ExternalToken, Forum, Submission, User, WSLog

router = APIRouter(tags=["Moodle-compatible web services"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class WSException(Exception):
    def __init__(self, errorcode: str, message: str, exception: str = "moodle_exception"):
        super().__init__(message)
        self.errorcode, self.message, self.exception = errorcode, message, exception


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def ts(dt: Optional[datetime]) -> int:
    return int(dt.timestamp()) if dt else 0


async def _params(request: Request) -> Dict[str, str]:
    params = dict(request.query_params)
    if request.method == "POST":
        form = await request.form()
        params.update({k: str(v) for k, v in form.items()})
    return params


def _array(params: Dict[str, str], name: str) -> List[str]:
    """courseids[0]=1&courseids[1]=2  ->  ['1', '2']   (also events[courseids][0]=1)."""
    pattern = re.compile(re.escape(name) + r"\[(\d+)\]$")
    items = sorted(((int(m.group(1)), v) for k, v in params.items() if (m := pattern.match(k))), key=lambda x: x[0])
    return [v for _, v in items]


def _ids(values: List[str]) -> List[int]:
    try:
        return [int(v) for v in values]
    except ValueError:
        raise WSException("invalidparameter", "Invalid parameter value detected")


def _my_course_ids(db: Session, user: User) -> List[int]:
    return [e.course_id for e in db.scalars(select(Enrolment).where(Enrolment.user_id == user.id))]


# ---------------------------------------------------------------------------
# Web-service functions
# ---------------------------------------------------------------------------
def core_webservice_get_site_info(db: Session, user: User, p: Dict[str, str]) -> Any:
    return {
        "sitename": settings.SITE_NAME,
        "username": user.username,
        "firstname": user.firstname,
        "lastname": user.lastname,
        "fullname": user.fullname,
        "lang": "en",
        "userid": user.id,
        "siteurl": settings.public_url(),
        "userpictureurl": "",
        "functions": [{"name": n, "version": settings.RELEASE} for n in FUNCTIONS],
        "release": settings.RELEASE,
        "version": "2024042200",
        "mobilecssurl": "",
    }


def core_enrol_get_users_courses(db: Session, user: User, p: Dict[str, str]) -> Any:
    userid = int(p.get("userid") or user.id)
    if userid != user.id and user.role != "admin":
        raise WSException("nopermissions", "Sorry, but you do not currently have permissions to do that.", "required_capability_exception")
    out = []
    for e in db.scalars(select(Enrolment).where(Enrolment.user_id == userid)):
        c = e.course
        out.append({
            "id": c.id, "shortname": c.shortname, "fullname": c.fullname, "displayname": c.fullname, "idnumber": c.shortname,
            "summary": c.summary, "summaryformat": 1, "visible": 1, "enrolledusercount": len(c.enrolments),
            "role": e.role, "lastaccess": ts(settings.now()),
        })
    return out


def mod_assign_get_assignments(db: Session, user: User, p: Dict[str, str]) -> Any:
    mine = set(_my_course_ids(db, user))
    requested = _ids(_array(p, "courseids")) or sorted(mine)
    courses, warnings = [], []
    for cid in requested:
        if cid not in mine:
            warnings.append({"item": "course", "itemid": cid, "warningcode": "1", "message": "No access rights in course context"})
            continue
        c = db.get(Course, cid)
        courses.append({
            "id": c.id, "fullname": c.fullname, "shortname": c.shortname, "timemodified": ts(settings.now()),
            "assignments": [
                {"id": a.id, "cmid": 1000 + a.id, "course": c.id, "name": a.name, "intro": f"<p>{a.intro}</p>", "introformat": 1,
                 "duedate": ts(a.duedate), "allowsubmissionsfromdate": ts(a.allowsubmissionsfromdate), "cutoffdate": 0,
                 "gradingduedate": 0, "timemodified": ts(a.timemodified), "nosubmissions": 0, "submissiondrafts": 0}
                for a in c.assignments
            ],
        })
    return {"courses": courses, "warnings": warnings}


def mod_assign_get_submission_status(db: Session, user: User, p: Dict[str, str]) -> Any:
    a = db.get(Assignment, int(p.get("assignid", 0) or 0))
    if a is None or a.course_id not in _my_course_ids(db, user):
        raise WSException("invalidrecord", "Can't find data record in database table assign.", "dml_missing_record_exception")
    sub = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.user_id == user.id))
    return {
        "lastattempt": {
            "submission": {"id": sub.id if sub else 0, "userid": user.id, "status": sub.status if sub else "new",
                           "timemodified": ts(sub.timemodified) if sub else 0, "assignment": a.id},
            "submissionsenabled": True, "caneditowner": True, "cansubmit": True,
        },
        "warnings": [],
    }


def core_calendar_get_calendar_events(db: Session, user: User, p: Dict[str, str]) -> Any:
    mine = set(_my_course_ids(db, user))
    requested = set(_ids(_array(p, "events[courseids]"))) or mine
    start = int(p.get("options[timestart]", 0) or 0)
    end = int(p.get("options[timeend]", 0) or 0)
    events = []
    for e in db.scalars(select(CalendarEvent).where(CalendarEvent.course_id.in_(requested & mine)).order_by(CalendarEvent.timestart)):
        t = ts(e.timestart)
        if (start and t < start) or (end and t > end):
            continue
        events.append({"id": e.id, "name": e.name, "description": e.description, "format": 1, "courseid": e.course_id,
                       "groupid": 0, "userid": 0, "modulename": "", "instance": 0, "eventtype": "course",
                       "timestart": t, "timeduration": e.duration_minutes * 60, "location": e.location, "visible": 1})
    # Assignment due dates also appear in the calendar, as in Moodle
    for a in db.scalars(select(Assignment).where(Assignment.course_id.in_(requested & mine))):
        t = ts(a.duedate)
        if (start and t < start) or (end and t > end):
            continue
        events.append({"id": 100000 + a.id, "name": f"{a.name} is due", "description": "", "format": 1, "courseid": a.course_id,
                       "groupid": 0, "userid": 0, "modulename": "assign", "instance": a.id, "eventtype": "due",
                       "timestart": t, "timeduration": 0, "location": "", "visible": 1})
    return {"events": sorted(events, key=lambda e: e["timestart"]), "warnings": []}


def mod_forum_get_forums_by_courses(db: Session, user: User, p: Dict[str, str]) -> Any:
    mine = set(_my_course_ids(db, user))
    requested = set(_ids(_array(p, "courseids"))) or mine
    return [
        {"id": f.id, "course": f.course_id, "type": f.type, "name": f.name, "intro": "", "introformat": 1,
         "numdiscussions": len(f.discussions), "cmid": 2000 + f.id}
        for f in db.scalars(select(Forum).where(Forum.course_id.in_(requested & mine)))
    ]


def mod_forum_get_forum_discussions(db: Session, user: User, p: Dict[str, str]) -> Any:
    f = db.get(Forum, int(p.get("forumid", 0) or 0))
    if f is None or f.course_id not in _my_course_ids(db, user):
        raise WSException("invalidrecord", "Can't find data record in database table forum.", "dml_missing_record_exception")
    return {
        "discussions": [
            {"id": d.id, "discussion": d.id, "name": d.subject, "subject": d.subject, "message": f"<p>{d.message}</p>", "messageformat": 1,
             "created": ts(d.created), "modified": ts(d.created), "timemodified": ts(d.created), "userid": d.user_id,
             "userfullname": d.user.fullname, "numreplies": 0, "pinned": False}
            for d in f.discussions
        ],
        "warnings": [],
    }


def core_course_get_courses_by_field(db: Session, user: User, p: Dict[str, str]) -> Any:
    """Course catalogue (Moodle: field = id | shortname, empty = every course)."""
    field, value = p.get("field", ""), p.get("value", "")
    stmt = select(Course).order_by(Course.shortname)
    if field == "id":
        stmt = stmt.where(Course.id == int(_ids([value])[0]))
    elif field == "shortname":
        stmt = stmt.where(func.upper(Course.shortname) == value.upper())
    elif field:
        raise WSException("invalidparameter", "Invalid parameter value detected")
    return {"courses": [{"id": c.id, "shortname": c.shortname, "fullname": c.fullname, "displayname": c.fullname, "summary": c.summary,
                         "summaryformat": 1, "visible": 1, "enrollmentmethods": ["self"]} for c in db.scalars(stmt)], "warnings": []}


def enrol_self_enrol_user(db: Session, user: User, p: Dict[str, str]) -> Any:
    """Self-enrolment: the signed-in student joins a course (Moodle enrol_self plugin)."""
    course = db.get(Course, _ids([p.get("courseid", "")])[0])
    if course is None:
        raise WSException("invalidrecord", "Can't find data record in database table course.", "dml_missing_record_exception")
    if user.role != "student":
        raise WSException("nopermissions", "Only students can enrol themselves.", "required_capability_exception")
    if not db.scalar(select(Enrolment).where(Enrolment.user_id == user.id, Enrolment.course_id == course.id)):
        db.add(Enrolment(user_id=user.id, course_id=course.id, role="student"))
        db.commit()
    return {"status": True, "warnings": []}


def local_unilearn_self_unenrol(db: Session, user: User, p: Dict[str, str]) -> Any:
    """Leave a course the student joined (Moodle: enrol/self:unenrolself; exposed by a small local plugin)."""
    cid = _ids([p.get("courseid", "")])[0]
    e = db.scalar(select(Enrolment).where(Enrolment.user_id == user.id, Enrolment.course_id == cid, Enrolment.role == "student"))
    if e:
        db.delete(e)
        db.commit()
    return {"status": True, "warnings": []}


FUNCTIONS: Dict[str, Callable] = {
    f.__name__: f for f in (
        core_webservice_get_site_info, core_enrol_get_users_courses, mod_assign_get_assignments,
        mod_assign_get_submission_status, core_calendar_get_calendar_events, mod_forum_get_forums_by_courses,
        mod_forum_get_forum_discussions, core_course_get_courses_by_field, enrol_self_enrol_user, local_unilearn_self_unenrol,
    )
}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
def _log(db: Session, username: Optional[str], function: str, status: str) -> None:
    db.add(WSLog(username=username, function=function, status=status, at=datetime.now()))
    db.commit()


class ProvisionStudent(BaseModel):
    email: EmailStr
    firstname: str = Field(..., min_length=1, max_length=100)
    lastname: str = Field("", max_length=100)
    password: str = Field(..., min_length=6, max_length=72)


@router.post("/admin/tool/provision/student", include_in_schema=False)
def provision_student(body: ProvisionStudent, x_provisioning_key: Optional[str] = Header(None), db: Session = Depends(get_db)):
    """
    Creates a student account (username = email). Only for Remind Me Bro, which signs students up:
    it sends the provisioning key kept in data/unilearn/provisioning.key. Not part of Moodle's API.
    """
    if not x_provisioning_key or not secrets.compare_digest(x_provisioning_key, settings.provisioning_key()):
        return JSONResponse({"error": "Invalid provisioning key"}, status_code=403)
    email = body.email.lower()
    if db.scalar(select(User).where(or_(func.lower(User.email) == email, func.lower(User.username) == email))):
        return JSONResponse({"error": "An account with this email already exists"}, status_code=409)
    user = User(username=email, email=email, firstname=body.firstname.strip(), lastname=body.lastname.strip() or "-",
                role="student", password_hash=pwd_context.hash(body.password))
    db.add(user)
    db.commit()
    _log(db, email, "provision/student", "ok")
    return {"id": user.id, "username": user.username}


@router.api_route("/login/token.php", methods=["GET", "POST"], summary="Get a web-service token (Moodle login/token.php)")
async def token_php(request: Request, db: Session = Depends(get_db)):
    p = await _params(request)
    username, password, service = p.get("username", "").strip().lower(), p.get("password", ""), p.get("service", "")
    user = db.scalar(select(User).where(or_(func.lower(User.username) == username, func.lower(User.email) == username)))
    if user is None or not pwd_context.verify(password, user.password_hash):
        _log(db, username or None, "login/token.php", "invalidlogin")
        return JSONResponse({"error": "Invalid login, please try again", "errorcode": "invalidlogin", "stacktrace": None, "debuginfo": None, "reproductionlink": None})
    if service != settings.MOBILE_SERVICE:
        _log(db, user.username, "login/token.php", "servicenotavailable")
        return JSONResponse({"error": "Web service is not available (it doesn't exist or might be disabled)", "errorcode": "servicenotavailable"})
    token = secrets.token_hex(16)  # Moodle tokens are 32 hex characters
    db.add(ExternalToken(token_hash=sha256(token), token_hint=token[-4:], user_id=user.id, service=service,
                         client_name=request.headers.get("x-client-name") or request.headers.get("user-agent", "")[:120], created=datetime.now()))
    _log(db, user.username, "login/token.php", "ok")
    return {"token": token, "privatetoken": None}


@router.api_route("/webservice/rest/server.php", methods=["GET", "POST"], summary="REST web-service entry point (Moodle server.php)")
async def server_php(request: Request, db: Session = Depends(get_db)):
    p = await _params(request)
    fn_name = p.get("wsfunction", "")
    tok = db.scalar(select(ExternalToken).where(ExternalToken.token_hash == sha256(p.get("wstoken", ""))))
    if tok is None:
        _log(db, None, fn_name or "?", "invalidtoken")
        return JSONResponse({"exception": "moodle_exception", "errorcode": "invalidtoken", "message": "Invalid token - token not found"})
    if p.get("moodlewsrestformat", "xml") != "json":
        return JSONResponse({"exception": "moodle_exception", "errorcode": "invalidparameter",
                             "message": "This demo only supports moodlewsrestformat=json"})
    fn = FUNCTIONS.get(fn_name)
    if fn is None:
        _log(db, tok.user.username, fn_name or "?", "invalidrecord")
        return JSONResponse({"exception": "dml_missing_record_exception", "errorcode": "invalidrecord",
                             "message": "Can't find data record in database table external_functions."})
    tok.lastaccess = datetime.now()
    try:
        result = fn(db, tok.user, p)
    except WSException as exc:
        _log(db, tok.user.username, fn_name, exc.errorcode)
        return JSONResponse({"exception": exc.exception, "errorcode": exc.errorcode, "message": exc.message})
    _log(db, tok.user.username, fn_name, "ok")
    return JSONResponse(result)
