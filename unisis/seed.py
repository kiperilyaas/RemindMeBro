"""Starting data for UniSIS: the degree programme, the two terms of the current academic year and two accounts.

The demo courses are created without timetable, exams or grades: the Student Office adds those in /staff.
The terms are computed from today's date, so the calendar always starts from now.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from unisis import security
from unisis.config import settings
from unisis.models import Course, OAuthClient, Programme, Term, User

logger = logging.getLogger("unisis")


def public_url() -> str:
    return os.getenv("UNISIS_PUBLIC_URL", "http://127.0.0.1:8100").rstrip("/")


def academic_terms(today: date) -> list[Term]:
    """Winter and summer term of the academic year that contains `today` (the year starts in September)."""
    y = today.year if today.month >= 9 else today.year - 1
    return [
        Term(code=f"W{y}", name=f"Winter term {y}/{str(y + 1)[2:]}", starts_on=date(y, 9, 21), ends_on=date(y + 1, 1, 31)),
        Term(code=f"S{y + 1}", name=f"Summer term {y}/{str(y + 1)[2:]}", starts_on=date(y + 1, 2, 22), ends_on=date(y + 1, 6, 30)),
    ]


# Courses of the demo (codes of the Prague University of Economics and Business).
# Only code, name, teacher and room: lessons, assignments and exams are added from the staff area.
COURSES = [
    # code, name, lecturer, room
    ("2PR515", "Corporate Governance", "Chiara Neri", "SB 408"),
    ("2IB468", "Ethics in Finance", "Chiara Neri", "SB 410"),
    ("2MO522", "Financial Strategies in International Business", "Chiara Neri", "SB 411"),
    ("2IB421", "Global ESG and Implications for Sustainable Business", "Chiara Neri", "SB 412"),
    ("3SG712", "Growth strategies", "Marco Rossi", "SB 413"),
    ("3PA662", "Human Resource Management Seminar", "Marco Rossi", "SB 414"),
    ("3MA674", "International Management", "Marco Rossi", "SB 415"),
    ("3PO643", "Social Entrepreneurship: Innovation and Impact", "Marco Rossi", "SB 416"),
]


def seed_courses(db: Session) -> int:
    """Adds the demo courses that are missing (by code) to the current term as electives: nobody is enrolled,
    students choose them while course registration is open (opened here if it was never scheduled). No weekly classes."""
    from unisis.services import current_term   # local import: services imports models only
    term = current_term(db)
    if term is None:
        return 0
    if term.registration_opens_at is None:
        now = settings.now()
        term.registration_opens_at = now.replace(second=0, microsecond=0)
        term.registration_closes_at = (now + timedelta(days=30)).replace(hour=23, minute=59, second=0, microsecond=0)
    added = 0
    for code, name, lecturer, room in COURSES:
        if db.scalar(select(Course).where(Course.code == code)):
            continue
        db.add(Course(code=code, name=name, credits=6, term_id=term.id, lecturer_name=lecturer, capacity=100, kind="elective",
                      year_of_study=1, room=room))
        added += 1
    db.flush()
    return added


def rotate_staff_passwords(db: Session) -> int:
    """The Student Office never keeps the shared demo password: new random one in data/unisis/STAFF-PASSWORDS.txt."""
    from unisis.config import UNISIS_DIR
    from unisis.staff_passwords import new_password, write_password_file
    rotated = []
    for u in db.scalars(select(User).where(User.role == "registrar")):
        if security.verify_password(settings.DEMO_PASSWORD, u.password_hash):
            pw = new_password()
            u.password_hash = security.hash_password(pw)
            rotated.append((u.username, pw))
    if rotated:
        db.flush()
        write_password_file(UNISIS_DIR / "STAFF-PASSWORDS.txt", "UniSIS · Student Office (http://127.0.0.1:8100/staff)", rotated)
        logger.info("New password for the UniSIS Student Office: see %s", UNISIS_DIR / "STAFF-PASSWORDS.txt")
    return len(rotated)


def ensure_current_terms(db: Session) -> int:
    """Adds the terms of the current academic year if they are missing (data is kept across years)."""
    added = 0
    for t in academic_terms(settings.now().date()):
        if db.scalar(select(Term).where(Term.code == t.code)) is None:
            db.add(t)
            added += 1
    return added


def seed(db: Session) -> None:
    pw = security.hash_password(settings.DEMO_PASSWORD)
    prog = Programme(code="BSC-EF", name="Economics and Finance", degree="BSc", total_credits=180)
    db.add(prog)
    db.add_all(academic_terms(settings.now().date()))   # course registration windows stay closed until the Student Office opens them
    db.flush()
    db.add_all([
        User(username="registrar", email="registrar@unisis.demo", full_name="Student Office", role="registrar", password_hash=pw),
        User(username="giulia.esposito", email="giulia.esposito@unisis.demo", full_name="Giulia Esposito", role="student",
             password_hash=pw, student_number="EF-2026-0142", programme_id=prog.id, year_of_study=1),
    ])
    db.flush()
    n = seed_courses(db)
    logger.info("UniSIS starts with the programme, 2 terms, 2 accounts and %s courses (no timetable yet)", n)


def ensure_hub_client(db: Session) -> None:
    """Registers Remind Me Bro as an OAuth client and exports its credentials for the hub."""
    client = db.scalar(select(OAuthClient).where(OAuthClient.client_id == settings.HUB_CLIENT_ID))
    if client is None:
        client = OAuthClient(
            client_id=settings.HUB_CLIENT_ID,
            name="Remind Me Bro",
            description="Academic Unified Hub & AI Assistant: deadlines, timetable and exams in one place.",
            secret_hash="", secret_hint="", api_key_hash="", api_key_hint="",
            redirect_uris="\n".join([
                f"http://127.0.0.1:8000{settings.HUB_CALLBACK_PATH}",
                f"http://localhost:8000{settings.HUB_CALLBACK_PATH}",
            ]),
            allowed_scopes=" ".join(security.SCOPES),
        )
        db.add(client)
    if client.secret_hash and security.exported_credentials_valid(client):
        return
    secret = security.rotate_client_secret(client)
    api_key = security.rotate_api_key(client)
    db.flush()
    security.export_credentials(client, public_url(), secret=secret, api_key=api_key)
    logger.info("Client '%s' registered; credentials exported to %s", client.client_id, settings.CREDENTIALS_DIR)
