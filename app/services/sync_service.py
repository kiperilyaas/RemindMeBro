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

from app.database.models import Announcement, Course, Deadline, DeadlineDone, Event, MessageDateChoice, SourceType
from app.mocks import moodle_mock
from app.services import llm_extractor, unicomms_client, unilearn_client, unisis_client, vector_store

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
    owner_id: Optional[int] = None,
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
    ann.user_id = owner_id
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
                "owner_id": owner_id,   # personal Outlook/Teams message: only its owner's assistant may read it
            },
        )
    except Exception as exc:
        logger.warning("Indicizzazione ChromaDB fallita per %s: %s", external_id, exc)
        return ann, str(exc)
    return ann, None


def delete_announcement(db: Session, ann: Announcement) -> None:
    """Cancella un messaggio con le scadenze che l'AI ci aveva trovato (e lo toglie da ChromaDB)."""
    found = list(db.scalars(select(Deadline).where(Deadline.announcement_id == ann.id)))
    ids = [d.id for d in found]
    if ids:
        for d in db.scalars(select(Deadline).where(Deadline.superseded_by_id.in_(ids))):
            d.superseded_by_id = None   # an official date hidden by this message comes back
        for row in db.scalars(select(DeadlineDone).where(DeadlineDone.deadline_id.in_(ids))):
            db.delete(row)
        for row in db.scalars(select(MessageDateChoice).where(MessageDateChoice.deadline_id.in_(ids))):
            db.delete(row)
        for d in found:
            db.delete(d)
    try:
        vector_store.delete_documents([f"{ann.source.value}:{ann.external_id}"])
    except Exception as exc:  # the vector DB never blocks a delete
        logger.warning("ChromaDB: avviso %s non tolto dall'indice: %s", ann.external_id, exc)
    db.delete(ann)
    db.flush()


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
    owner_id: Optional[int] = None,
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
        owner_id=owner_id,
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
            owner_id=owner_id,
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

    # --- UniComms: lecturers' Teams posts and Outlook emails -> ChromaDB + estrazione AI ---
    teams_details: List[Dict[str, Any]] = []
    email_details: List[Dict[str, Any]] = []
    try:
        uc = unicomms_client.sync_messages(db, run_ai=True)
        for d in uc["ai_details"]:
            (email_details if d.get("source") == SourceType.EMAIL.value else teams_details).append(d)
    except unicomms_client.UniCommsError as exc:
        db.rollback()
        summary["errors"].append(f"UniComms: {exc}")

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


def prune_vector_store(db: Session) -> int:
    """At start-up: messages deleted from the database leave the assistant's index too."""
    keep = {f"{s.value}:{e}" for s, e in db.execute(select(Announcement.source, Announcement.external_id))}
    try:
        gone = [i for i in vector_store.all_ids() if i not in keep]
        vector_store.delete_documents(gone)
    except Exception as exc:  # the vector DB never blocks the start
        logger.warning("ChromaDB non ripulito: %s", exc)
        return 0
    if gone:
        logger.info("ChromaDB: tolti %s avvisi che non esistono più", len(gone))
    return len(gone)


def repair_wrong_moves(db: Session) -> int:
    """At start-up: an official date hidden by a message about something else (old rule that also read the AI's description)
    comes back. Only the titles count now (llm_extractor.titles_match)."""
    fixed = 0
    for d in db.scalars(select(Deadline).where(Deadline.superseded_by_id.is_not(None), Deadline.extracted_by_ai.is_(False))):
        newer = db.get(Deadline, d.superseded_by_id)
        if newer is not None and newer.extracted_by_ai and newer.announcement_id and not llm_extractor.titles_match(d.title, newer.title):
            d.superseded_by_id = None
            fixed += 1
    if fixed:
        db.commit()
        logger.info("%s data ufficiale/i tornata/e visibile/i (spostamento sbagliato da un messaggio)", fixed)
    return fixed


def move_demo_courses(db: Session) -> int:
    """Existing data: a course still taught by its old demo lecturer goes to the new one (and to their hub account)."""
    from app.database.models import User   # local import: only needed here
    moved = 0
    for code, old, new in moodle_mock.MOVED_COURSES:
        course = _course_by_code(db, code)
        if course is None or course.professor != old:
            continue
        old_user = course.professor_user
        if old_user is not None and old_user.full_name != old:
            continue   # the course belongs to a lecturer who took it in the hub: keep it
        course.professor = new
        course.professor_id = db.scalar(select(User.id).where(User.full_name == new))
        moved += 1
    if moved:
        db.flush()
        logger.info("%s corsi demo passati ai nuovi docenti", moved)
    return moved


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
    move_demo_courses(db)
    db.commit()
    repair_wrong_moves(db)
    prune_vector_store(db)
    if seed_users:
        info["demo_users_created"] = seed_demo_users(db)
    else:
        link_all_professors(db)
        db.commit()
    return info
