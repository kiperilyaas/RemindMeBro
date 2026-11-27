"""Starting data for UniLearn: accounts and the demo courses (no assignments, announcements or events: they are created in /staff)."""
from __future__ import annotations

import logging

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from unilearn.config import settings
from sqlalchemy import select

from unilearn.models import Course, Enrolment, Forum, User

logger = logging.getLogger("unilearn")
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TEACHERS = [
    ("marco.rossi", "Marco", "Rossi"),
    ("laura.bianchi", "Laura", "Bianchi"),
    ("giovanni.verdi", "Giovanni", "Verdi"),
    ("chiara.neri", "Chiara", "Neri"),
    ("paolo.conti", "Paolo", "Conti"),
]


# Courses of the demo (codes of the Prague University of Economics and Business).
# Only code, name, teacher and room: lessons, assignments and exams are added from the staff area.
COURSES = [
    # code, name, teacher username, room
    ("2PR515", "Corporate Governance", "chiara.neri", "SB 408"),
    ("2IB468", "Ethics in Finance", "chiara.neri", "SB 410"),
    ("2MO522", "Financial Strategies in International Business", "laura.bianchi", "SB 411"),
    ("2IB421", "Global ESG and Implications for Sustainable Business", "laura.bianchi", "SB 412"),
    ("3SG712", "Growth strategies", "marco.rossi", "SB 413"),
    ("3PA662", "Human Resource Management Seminar", "marco.rossi", "SB 414"),
    ("3MA674", "International Management", "giovanni.verdi", "SB 415"),
    ("3PO643", "Social Entrepreneurship: Innovation and Impact", "paolo.conti", "SB 416"),
]

# Until 26 November 2026 Chiara Neri and Marco Rossi taught all eight courses: (code, old teacher, new teacher).
MOVED_COURSES = [
    ("2MO522", "chiara.neri", "laura.bianchi"),
    ("2IB421", "chiara.neri", "laura.bianchi"),
    ("3MA674", "marco.rossi", "giovanni.verdi"),
    ("3PO643", "marco.rossi", "paolo.conti"),
]


def move_demo_courses(db: Session) -> int:
    """Existing data: a course still taught by its old demo teacher goes to the new one (a teacher chosen in /staff is kept)."""
    moved = 0
    for code, old, new in MOVED_COURSES:
        course = db.scalar(select(Course).where(Course.shortname == code))
        old_u = db.scalar(select(User).where(User.username == old))
        new_u = db.scalar(select(User).where(User.username == new))
        if not (course and old_u and new_u):
            continue
        teachers = list(db.scalars(select(Enrolment).where(Enrolment.course_id == course.id, Enrolment.role == "editingteacher")))
        if [t.user_id for t in teachers] != [old_u.id]:
            continue
        if db.scalar(select(Enrolment).where(Enrolment.course_id == course.id, Enrolment.user_id == new_u.id)) is None:
            teachers[0].user_id = new_u.id
        else:
            db.delete(teachers[0])
        moved += 1
    if moved:
        db.flush()
        logger.info("%s demo course(s) moved to their new teachers", moved)
    return moved


def seed_courses(db: Session) -> int:
    """Adds the demo courses that are missing (by code). Nobody is enrolled: students join the courses they choose in UniSIS."""
    added = 0
    for code, name, teacher, room in COURSES:
        if db.scalar(select(Course).where(Course.shortname == code)):
            continue
        t = db.scalar(select(User).where(User.username == teacher))
        c = Course(shortname=code, fullname=name, summary="", room=room)
        db.add(c)
        db.flush()
        db.add(Forum(course_id=c.id, type="news", name="Announcements"))
        if t:
            db.add(Enrolment(user_id=t.id, course_id=c.id, role="editingteacher"))
        added += 1
    db.flush()
    return added


def rotate_staff_passwords(db: Session) -> int:
    """Admin and teachers never keep the shared demo password: new random ones go to data/unilearn/STAFF-PASSWORDS.txt."""
    from unilearn.config import UNILEARN_DIR
    from unilearn.staff_passwords import new_password, write_password_file
    rotated = []
    for u in db.scalars(select(User).where(User.role.in_(["admin", "teacher"]))):
        if pwd_context.verify(settings.DEMO_PASSWORD, u.password_hash):
            pw = new_password()
            u.password_hash = pwd_context.hash(pw)
            rotated.append((u.username, pw))
    if rotated:
        db.flush()
        write_password_file(UNILEARN_DIR / "STAFF-PASSWORDS.txt", "UniLearn · admin and teachers (http://127.0.0.1:8200/staff)", rotated)
        logger.info("New passwords for %s UniLearn staff account(s): see %s", len(rotated), UNILEARN_DIR / "STAFF-PASSWORDS.txt")
    return len(rotated)


def seed(db: Session) -> None:
    pw = pwd_context.hash(settings.DEMO_PASSWORD)
    users = [User(username="admin", email="admin@unilearn.demo", firstname="Site", lastname="Administrator", role="admin", password_hash=pw)]
    for username, first, last in TEACHERS:
        users.append(User(username=username, email=f"{username}@unilearn.demo", firstname=first, lastname=last, role="teacher", password_hash=pw))
    users.append(User(username="giulia.esposito", email="giulia.esposito@unilearn.demo", firstname="Giulia", lastname="Esposito",
                      role="student", password_hash=pw))
    db.add_all(users)
    db.flush()
    n = seed_courses(db)
    logger.info("UniLearn starts with %s accounts and %s courses (no assignments yet)", len(users), n)
