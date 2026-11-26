"""
STEP 5 - Pipeline di sincronizzazione e normalizzazione.

UniLearn (Moodle web services, token dello studente)
    compiti + stato consegna -> Deadline      eventi del corso -> Event
    forum Announcements      -> Announcement + ChromaDB + llama3.2 (scadenze nascoste)
Teams / email (testo informale) -> llama3.2 -> scadenze estratte -> SQLite
UniSIS (OAuth 2.0)              -> orario, appelli, finestre di iscrizione (dati personali)

La pipeline è idempotente: rieseguirla aggiorna i record esistenti
invece di duplicarli (chiave: source + external_id).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Announcement, Course, Deadline, Event, SourceType
from app.mocks import moodle_mock, teams_mock
from app.services import llm_extractor, unilearn_client, unisis_client, vector_store

# Import ritardato per evitare cicli: auth dipende solo da DB/schemi
from app.api.auth import link_all_professors, seed_demo_users  # noqa: E402
from app.services.sync_lock import exclusive

logger = logging.getLogger(__name__)

DT_FMT = "%Y-%m-%d %H:%M"


def _parse_dt(value: str) -> datetime:
    return datetime.strptime(value, DT_FMT)


def _course_by_code(db: Session, code: Optional[str]) -> Optional[Course]:
    if not code:
        return None
    return db.scalar(select(Course).where(Course.code == code))


def ensure_course(db: Session, code: Optional[str], name: Optional[str] = None) -> Optional[Course]:
    """Returns the hub course with this code, creating it when a connected system knows it and the hub does not."""
    if not code:
        return None
    course = _course_by_code(db, code)
    if course is None and name:
        course = Course(code=code, name=name, professor="")
        db.add(course)
        db.flush()
    return course


# ---------------------------------------------------------------------------
# Moodle
# ---------------------------------------------------------------------------
def sync_moodle_courses(db: Session) -> int:
    count = 0
    for c in moodle_mock.get_courses():
        course = _course_by_code(db, c["code"])
        if course is None:
            course = Course(code=c["code"], name=c["name"], professor=c["professor"])
            db.add(course)
        elif not course.professor and course.professor_id is None:
            course.professor = c["professor"]   # a course that came from UniLearn/UniSIS gets its lecturer; its name is kept
        count += 1
    db.flush()
    return count


# ---------------------------------------------------------------------------
# Avvisi (comuni a Moodle forum e Teams)
# ---------------------------------------------------------------------------
def upsert_announcement(
    db: Session,
    *,
    external_id: str,
    source: SourceType,
    author: str,
    content: str,
    created_at: datetime,
    course: Optional[Course],
    author_id: Optional[int] = None,
) -> tuple[Announcement, Optional[str]]:
    """
    Salva l'avviso in SQLite e lo indicizza in ChromaDB.
    Ritorna (announcement, errore_vector_db | None): un problema del vector DB
    non deve bloccare né il salvataggio relazionale né l'estrazione AI.
    """
    ann = db.scalar(
        select(Announcement).where(Announcement.source == source, Announcement.external_id == external_id)
    )
    if ann is None:
        ann = Announcement(source=source, external_id=external_id)
        db.add(ann)
    ann.author = author
    ann.content = content
    ann.created_at = created_at
    ann.course_id = course.id if course else None
    if author_id is not None:
        ann.author_id = author_id
    db.flush()

    try:
        vector_store.add_announcement_to_vector_db(
            id=f"{source.value}:{external_id}",
            text=content,
            metadata={
                "source": source.value,
                "author": author,
                "course_code": course.code if course else None,
                "course_name": course.name if course else None,
                "created_at": created_at.strftime(DT_FMT),
                "announcement_id": ann.id,
            },
        )
    except Exception as exc:
        logger.warning("Indicizzazione ChromaDB fallita per %s: %s", external_id, exc)
        return ann, str(exc)
    return ann, None


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
def process_informal_message(
    db: Session,
    *,
    external_id: str,
    content: str,
    author: str,
    created_at: datetime,
    course_code: Optional[str],
    source: SourceType = SourceType.TEAMS,
    author_id: Optional[int] = None,
    course_is_certain: bool = False,
) -> Dict[str, Any]:
    """
    Gestisce un singolo messaggio informale:
    1. SQLite (Announcement) + ChromaDB
    2. llama3.2 -> eventuale scadenza -> SQLite (Deadline, collegata all'avviso)
    Ritorna un dettaglio leggibile per il riepilogo della demo.

    `course_is_certain=True` (avviso pubblicato da un docente nel proprio corso)
    forza il corso invece di affidarsi al nome proposto dall'LLM.
    """
    course = _course_by_code(db, course_code)
    ann, vector_error = upsert_announcement(
        db,
        external_id=external_id,
        source=source,
        author=author,
        content=content,
        created_at=created_at,
        course=course,
        author_id=author_id,
    )

    detail: Dict[str, Any] = {
        "message_id": external_id,
        "announcement_id": ann.id,
        "author": author,
        "text": content,
        "indexed_in_vector_db": vector_error is None,
    }
    if vector_error:
        detail["vector_db_error"] = vector_error
    started = time.perf_counter()
    try:
        result = llm_extractor.extract_and_save_deadline(
            db,
            content,
            source=source,
            external_id=external_id,
            fallback_course_code=course_code,
            force_course_code=course_code if course_is_certain else None,
            announcement_id=ann.id,
        )
        detail.update(
            {
                "status": "deadline_extracted" if result.saved_deadline_id else "no_deadline",
                "extraction": result.extraction.model_dump(mode="json"),
                "raw_llm_output": result.raw_llm_output,
                "saved_deadline_id": result.saved_deadline_id,
                "matched_course": result.matched_course_name,
                "updates_existing": result.updates_existing,
            }
        )
    except llm_extractor.LLMUnavailableError as exc:
        detail.update({"status": "llm_unavailable", "error": str(exc)})
    except llm_extractor.LLMParsingError as exc:
        detail.update({"status": "parsing_error", "error": str(exc)})
    detail["llm_seconds"] = round(time.perf_counter() - started, 2)
    return detail


def sync_teams(db: Session) -> List[Dict[str, Any]]:
    details = []
    for m in teams_mock.get_channel_messages():
        details.append(
            process_informal_message(
                db,
                external_id=m["id"],
                content=m["content"],
                author=m["author"],
                created_at=_parse_dt(m["created"]),
                course_code=m.get("channel_course_code"),
            )
        )
        db.commit()  # commit per messaggio: un errore LLM non annulla il lavoro precedente
    return details


def sync_emails(db: Session) -> List[Dict[str, Any]]:
    """Email istituzionali: stesso trattamento dei messaggi Teams (ChromaDB + estrazione AI)."""
    details = []
    for m in teams_mock.get_emails():
        details.append(
            process_informal_message(
                db,
                external_id=m["id"],
                content=m["content"],
                author=m["author"],
                created_at=_parse_dt(m["created"]),
                course_code=m.get("course_code"),
                source=SourceType.EMAIL,
            )
        )
        db.commit()
    return details


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
@exclusive
def run_sync_pipeline(db: Session, user: Optional[Any] = None) -> Dict[str, Any]:
    """Esegue l'intera pipeline e ritorna un riepilogo per la demo (+ UniSIS dell'utente, se collegato)."""
    started = time.perf_counter()
    summary: Dict[str, Any] = {"errors": []}

    # --- Catalogo corsi (collega i corsi ai docenti registrati) ---
    summary["courses_imported"] = sync_moodle_courses(db)
    link_all_professors(db)
    db.commit()

    # --- UniSIS first: the courses the student chose there are the ones followed in UniLearn ---
    if user is not None and unisis_client.get_connection(db, user) is not None:
        try:
            summary["unisis"] = unisis_client.sync_user(db, user)
        except unisis_client.UniSISError as exc:
            summary["unisis"] = {"status": "error", "error": str(exc)}
            summary["errors"].append(f"UniSIS: {exc}")

    # --- UniLearn (Moodle-compatible): compiti, eventi, avvisi -- solo se collegato ---
    summary["moodle_deadlines_imported"] = 0
    summary["events_imported"] = 0
    summary["moodle_announcements_indexed"] = 0
    forum_details: List[Dict[str, Any]] = []
    ul_conn = unilearn_client.get_connection(db, user) if user is not None else None
    if ul_conn is not None and ul_conn.status != "connected":
        summary["unilearn"] = {"status": ul_conn.status}
        summary["errors"].append("UniLearn: the access token was deleted. Connect UniLearn again from Connections.")
    elif ul_conn is not None:
        try:
            ul = unilearn_client.sync_user(db, user, run_ai=True)
            forum_details = ul.pop("ai_details", [])
            summary["unilearn"] = ul
            summary["moodle_deadlines_imported"] = ul["assignments"]
            summary["events_imported"] = ul["events"]
            summary["moodle_announcements_indexed"] = ul["posts"]
        except unilearn_client.UniLearnError as exc:
            db.rollback()
            summary["unilearn"] = {"status": "error", "error": str(exc)}
            summary["errors"].append(f"UniLearn: {exc}")

    # --- Teams + Email: ChromaDB + estrazione AI ---
    try:
        teams_details = sync_teams(db)
    except Exception as exc:
        db.rollback()
        logger.exception("Errore sincronizzazione Teams")
        teams_details = []
        summary["errors"].append(f"Teams: {exc}")
    try:
        email_details = sync_emails(db)
    except Exception as exc:
        db.rollback()
        logger.exception("Errore sincronizzazione email")
        email_details = []
        summary["errors"].append(f"Email: {exc}")

    all_details = forum_details + teams_details + email_details
    summary["teams_messages_processed"] = len(teams_details)
    summary["emails_processed"] = len(email_details)
    summary["ai_deadlines_extracted"] = sum(1 for d in all_details if d.get("status") == "deadline_extracted")
    summary["ai_details"] = all_details
    summary["vector_documents_total"] = vector_store.count_documents()
    summary["teams_messages_indexed"] = sum(1 for d in all_details if d.get("indexed_in_vector_db"))
    for d in all_details:
        if d.get("status") in {"llm_unavailable", "parsing_error"}:
            summary["errors"].append(f"{d['message_id']}: {d.get('error')}")
        if d.get("vector_db_error"):
            summary["errors"].append(f"{d['message_id']} (vector DB): {d['vector_db_error']}")
    # --- UniSIS: personal timetable, exams and registration windows (only if connected) ---
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    return summary


def bootstrap_demo_data(db: Session, seed_users: bool = True) -> Dict[str, Any]:
    """
    Avvio dell'app: se il DB è vuoto importa subito i dati *strutturati* di Moodle
    (nessun LLM, istantaneo) così il frontend non parte vuoto, poi crea gli account demo.
    La parte AI (Teams + estrazione) resta affidata a POST /api/sync.
    """
    info: Dict[str, Any] = {"imported": False, "demo_users_created": []}
    if db.scalar(select(Course.id).limit(1)) is None:
        sync_moodle_courses(db)   # assignments and events arrive when a student connects UniLearn
        db.commit()
        info["imported"] = True
    if seed_users:
        info["demo_users_created"] = seed_demo_users(db)
    else:
        link_all_professors(db)
        db.commit()
    return info
