"""Who can write and to which courses: the demo lecturers and courses (same as UniLearn, UniSIS and the hub)."""
from __future__ import annotations

from typing import Dict, List, Optional

# username, display name
LECTURERS = [
    ("chiara.neri", "Prof. Chiara Neri"),
    ("laura.bianchi", "Prof. Laura Bianchi"),
    ("marco.rossi", "Prof. Marco Rossi"),
    ("giovanni.verdi", "Prof. Giovanni Verdi"),
    ("paolo.conti", "Prof. Paolo Conti"),
]

# code, name, lecturer username (same split as unilearn/seed.py)
COURSES = [
    ("2PR515", "Corporate Governance", "chiara.neri"),
    ("2IB468", "Ethics in Finance", "chiara.neri"),
    ("2MO522", "Financial Strategies in International Business", "laura.bianchi"),
    ("2IB421", "Global ESG and Implications for Sustainable Business", "laura.bianchi"),
    ("3SG712", "Growth strategies", "marco.rossi"),
    ("3PA662", "Human Resource Management Seminar", "marco.rossi"),
    ("3MA674", "International Management", "giovanni.verdi"),
    ("3PO643", "Social Entrepreneurship: Innovation and Impact", "paolo.conti"),
]

# students a lecturer can write to one by one (any other address can be typed)
STUDENTS = [("student@demo.it", "Giulia Esposito")]


def lecturer(username: str) -> Optional[Dict[str, str]]:
    from unicomms.config import settings
    for i, (u, name) in enumerate(LECTURERS, start=1):
        if u == username:
            return {"id": i, "username": u, "fullname": name, "email": f"{u}@{settings.MAIL_DOMAIN}"}
    return None


def lecturer_by_id(uid: int) -> Optional[Dict[str, str]]:
    return lecturer(LECTURERS[uid - 1][0]) if 1 <= uid <= len(LECTURERS) else None


def courses_for(username: str) -> List[Dict[str, object]]:
    """Every course, the lecturer's own first."""
    out = [{"code": c, "name": n, "mine": t == username} for c, n, t in COURSES]
    return sorted(out, key=lambda x: (not x["mine"], x["name"]))
