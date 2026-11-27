"""
Catalogo corsi "mock" di Moodle: i corsi della demo, senza compiti né lezioni.

Serve a collegare i docenti dell'hub ai loro corsi (stesso nome). Compiti, eventi e
avvisi arrivano da UniLearn, orario ed esami da UniSIS, quando lo studente li collega.
Altri corsi: area docente → New course, oppure arrivano da UniLearn/UniSIS con il loro codice.
"""
from typing import Any, Dict, List

COURSES = [
    ("2PR515", "Corporate Governance", "Prof. Chiara Neri"),
    ("2IB468", "Ethics in Finance", "Prof. Chiara Neri"),
    ("2MO522", "Financial Strategies in International Business", "Prof. Laura Bianchi"),
    ("2IB421", "Global ESG and Implications for Sustainable Business", "Prof. Laura Bianchi"),
    ("3SG712", "Growth strategies", "Prof. Marco Rossi"),
    ("3PA662", "Human Resource Management Seminar", "Prof. Marco Rossi"),
    ("3MA674", "International Management", "Prof. Giovanni Verdi"),
    ("3PO643", "Social Entrepreneurship: Innovation and Impact", "Prof. Paolo Conti"),
]

# Until 26 November 2026 Chiara Neri and Marco Rossi taught all eight courses: (code, old lecturer, new lecturer).
MOVED_COURSES = [
    ("2MO522", "Prof. Chiara Neri", "Prof. Laura Bianchi"),
    ("2IB421", "Prof. Chiara Neri", "Prof. Laura Bianchi"),
    ("3MA674", "Prof. Marco Rossi", "Prof. Giovanni Verdi"),
    ("3PO643", "Prof. Marco Rossi", "Prof. Paolo Conti"),
]


def get_courses() -> List[Dict[str, Any]]:
    """Simula core_course_get_courses."""
    return [{"code": c, "name": n, "professor": p} for c, n, p in COURSES]
