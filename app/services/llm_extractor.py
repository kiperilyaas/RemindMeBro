"""
Servizi basati su LLM locale (Ollama + llama3.2).

1. extract_deadline_from_text(): Structured Extraction di scadenze da testo libero.
2. extract_and_save_deadline(): estrazione + persistenza in SQLite.
3. answer_student_query(): chatbot RAG (ChromaDB + SQLite -> llama3.2).
"""
from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import ollama
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import Announcement, Connection, Course, Deadline, DeadlineDone, Event, SourceType
from app.services import vector_store

logger = logging.getLogger(__name__)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Eccezioni
# ---------------------------------------------------------------------------
class LLMUnavailableError(RuntimeError):
    """Ollama non raggiungibile o modello non disponibile."""


class LLMStopped(RuntimeError):
    """The student pressed Stop: the answer was dropped and Ollama was told to stop."""


class LLMParsingError(ValueError):
    """L'LLM ha restituito un output non interpretabile come JSON."""


# ---------------------------------------------------------------------------
# Modello dell'output strutturato
# ---------------------------------------------------------------------------
class ExtractedDeadline(BaseModel):
    """Schema che l'LLM deve rispettare (validato con Pydantic)."""

    has_deadline: bool = False
    course_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None

    @field_validator("course_name", "title", "description", mode="before")
    @classmethod
    def _empty_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and v.strip().lower() in {"", "null", "none", "n/a"}:
            return None
        return v

    @field_validator("due_date", mode="before")
    @classmethod
    def _parse_due_date(cls, v: Any) -> Any:
        """Accetta più formati: ISO completo, 'YYYY-MM-DD HH:MM', solo data."""
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            s = v.strip().replace("Z", "")
            if s.lower() in {"", "null", "none"}:
                return None
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    return datetime.strptime(s[:19], fmt)
                except ValueError:
                    continue
            try:
                # Solo data -> scadenza a fine giornata
                d = datetime.strptime(s[:10], "%Y-%m-%d")
                return d.replace(hour=23, minute=59)
            except ValueError:
                pass
            try:
                return datetime.fromisoformat(s)
            except ValueError:
                return None  # data illeggibile -> trattata come assente
        return None

    @model_validator(mode="after")
    def _consistency(self) -> "ExtractedDeadline":
        # Una scadenza senza data non è utilizzabile: la scartiamo
        if self.has_deadline and self.due_date is None:
            self.has_deadline = False
        if self.has_deadline and not self.title:
            self.title = "Deadline from message"
        return self


class ExtractionResult(BaseModel):
    """Risultato completo di estrazione + salvataggio (usato dalle API)."""

    extraction: ExtractedDeadline
    raw_llm_output: str = ""
    saved_deadline_id: Optional[int] = None
    matched_course_id: Optional[int] = None
    matched_course_name: Optional[str] = None
    updates_existing: Optional[Dict[str, Any]] = Field(
        default=None,
        description="If the deadline appears to move an existing Moodle deadline, the comparison is here.",
    )


# ---------------------------------------------------------------------------
# Client Ollama
# ---------------------------------------------------------------------------
_client: Optional[ollama.Client] = None


def get_ollama_client() -> ollama.Client:
    global _client
    if _client is None:
        _client = ollama.Client(host=settings.OLLAMA_HOST, timeout=settings.OLLAMA_TIMEOUT)
    return _client


def chat_long(messages: List[Dict[str, str]], options: Dict[str, Any], json_mode: bool = False,
              should_stop: Optional[Callable[[], bool]] = None) -> str:
    """
    One chat for a long job (Smart Notes, Ask the material), straight on Ollama's HTTP API.
    - Streamed: the wait limit (NOTES_TIMEOUT) counts from the last word received, so a slow computer that keeps
      writing is never cut off.
    - should_stop: checked twice a second, also while Ollama is still reading the text and has sent nothing yet.
      When it returns True the socket is shut down: the request ends here, Ollama sees the client leave and stops
      working on it, and LLMStopped is raised.
    """
    import json as _json
    import socket as _socket
    import threading
    import httpx
    body: Dict[str, Any] = {"model": settings.OLLAMA_MODEL, "messages": messages, "options": options, "stream": True}
    if json_mode:
        body["format"] = "json"
    socks: List[Any] = []
    done, stopped = threading.Event(), threading.Event()

    def trace(event: str, info: Dict[str, Any]) -> None:   # httpcore tells us the socket as soon as it connects
        if event == "connection.connect_tcp.complete" and info.get("return_value") is not None:
            sock = info["return_value"].get_extra_info("socket")
            if sock is not None:
                socks.append(sock)

    def watch() -> None:
        while not done.wait(0.5):
            if should_stop and should_stop():
                stopped.set()
                for sock in socks:
                    try:
                        sock.shutdown(_socket.SHUT_RDWR)   # wakes up the blocked read in the other thread
                    except OSError:
                        pass
                return

    if should_stop:
        threading.Thread(target=watch, name="ollama-stop-watch", daemon=True).start()
    parts: List[str] = []
    url = settings.OLLAMA_HOST.rstrip("/") + "/api/chat"
    try:
        with httpx.Client(timeout=httpx.Timeout(settings.NOTES_TIMEOUT, connect=10.0)) as client:
            with client.stream("POST", url, json=body, extensions={"trace": trace}) as r:
                if r.status_code != 200:
                    r.read()
                    try:
                        err = r.json().get("error") or r.text
                    except Exception:
                        err = r.text
                    raise ollama.ResponseError(err, r.status_code)
                for line in r.iter_lines():
                    if stopped.is_set():
                        raise LLMStopped("Stopped.")
                    if not line.strip():
                        continue
                    chunk = _json.loads(line)
                    if chunk.get("error"):
                        raise ollama.ResponseError(chunk["error"], 500)
                    parts.append((chunk.get("message") or {}).get("content") or "")
                    if chunk.get("done"):
                        break
    except LLMStopped:
        raise
    except Exception as exc:
        if stopped.is_set():
            raise LLMStopped("Stopped.") from exc
        _raise_long(exc)
    finally:
        done.set()
    if stopped.is_set():
        raise LLMStopped("Stopped.")
    return "".join(parts)


def _raise_long(exc: Exception) -> None:
    """Turns what went wrong in a long chat into a message the student can act on."""
    import httpx
    if isinstance(exc, ollama.ResponseError):
        raise LLMUnavailableError(f"Ollama returned an error ({exc.status_code}): {exc.error}") from exc
    if isinstance(exc, (httpx.ConnectError, ConnectionError)):
        raise LLMUnavailableError(f"The local AI is not running (Ollama at {settings.OLLAMA_HOST}). Start it and try again.") from exc
    if isinstance(exc, httpx.TimeoutException):
        minutes = round(settings.NOTES_TIMEOUT / 60)
        raise LLMUnavailableError(f"The local AI gave no answer for {minutes} minutes ({settings.OLLAMA_MODEL}). "
                                  "The file may be too long for this computer: try again, or set NOTES_TIMEOUT higher.") from exc
    raise LLMUnavailableError(f"The local AI stopped with an error: {exc}") from exc


def _chat(messages: List[Dict[str, str]], json_mode: bool = False, temperature: float = 0.0) -> str:
    """Wrapper unico attorno a ollama.chat() con gestione errori uniforme."""
    try:
        kwargs: Dict[str, Any] = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages,
            "options": {"temperature": temperature},
        }
        if json_mode:
            kwargs["format"] = "json"  # Ollama forza un output JSON sintatticamente valido
        response = get_ollama_client().chat(**kwargs)
        return response["message"]["content"] or ""
    except ollama.ResponseError as exc:
        raise LLMUnavailableError(
            f"Ollama returned an error ({exc.status_code}): {exc.error}. "
            f"Did you run `ollama pull {settings.OLLAMA_MODEL}`?"
        ) from exc
    except Exception as exc:  # ConnectError, timeout, ...
        raise LLMUnavailableError(
            f"Cannot reach Ollama at {settings.OLLAMA_HOST}: {exc}. "
            "Make sure `ollama serve` is running."
        ) from exc


def check_ollama() -> Dict[str, Any]:
    """Health-check: Ollama raggiungibile e modello presente?"""
    try:
        listed = get_ollama_client().list()
        models = listed.get("models", []) if isinstance(listed, dict) else getattr(listed, "models", [])
        names = []
        for m in models:
            name = m.get("model") or m.get("name") if isinstance(m, dict) else getattr(m, "model", None)
            if name:
                names.append(name)
        has_model = any(n.split(":")[0] == settings.OLLAMA_MODEL.split(":")[0] for n in names)
        return {"reachable": True, "model": settings.OLLAMA_MODEL, "model_available": has_model, "models": names}
    except Exception as exc:
        return {"reachable": False, "model": settings.OLLAMA_MODEL, "model_available": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Parsing robusto del JSON restituito dall'LLM
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)


def _first_json_object(text: str) -> Optional[str]:
    """Estrae il primo oggetto {...} bilanciato, ignorando le graffe dentro le stringhe."""
    start = text.find("{")
    while start != -1:
        depth, in_str, escape = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def parse_llm_json(raw: str) -> Dict[str, Any]:
    """
    Converte l'output dell'LLM in dict, tollerando:
    - blocchi ```json ... ``` o ``` ... ```
    - testo prima/dopo il JSON ("Ecco il risultato: {...}")
    - virgole finali prima di } o ]
    - True/False/None in stile Python
    """
    if not raw or not raw.strip():
        raise LLMParsingError("Empty LLM output")

    text = raw.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()

    candidates = [text]
    obj = _first_json_object(text)
    if obj and obj != text:
        candidates.append(obj)

    for candidate in candidates:
        for attempt in (candidate, _repair_json(candidate)):
            try:
                data = json.loads(attempt)
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    data = data[0]  # se l'LLM restituisce una lista, prendiamo il primo elemento
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
    raise LLMParsingError(f"The LLM returned invalid JSON: {raw[:300]!r}")


def _repair_json(text: str) -> str:
    """Riparazioni euristiche minime e sicure."""
    fixed = re.sub(r",\s*([}\]])", r"\1", text)  # trailing comma
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)
    fixed = re.sub(r"\bNone\b", "null", fixed)
    return fixed


# ---------------------------------------------------------------------------
# STEP 4 - Structured Extraction
# ---------------------------------------------------------------------------
EXTRACTION_SYSTEM_PROMPT = """You are a data extraction system for a university (Economics & Finance programme).
You read informal messages from lecturers and university offices (Teams, Moodle forum, email)
and identify DEADLINES (submissions, reports to send, registrations, final dates).
Messages may be written in English or Italian.

RULES:
- Reply ONLY with a valid JSON object, with no text before or after it and no ```.
- Use exactly these keys:
  {"has_deadline": bool, "course_name": string|null, "title": string|null,
   "description": string|null, "due_date": "YYYY-MM-DDTHH:MM:SS"|null}
- A cancelled lecture or office hours are NOT deadlines.
- If there are several deadlines, extract only the main (most important) one.
- Resolve relative dates ("tomorrow", "next Friday") using the REFERENCE DATE.
- If the year is missing, use the first future occurrence after the reference date.
- If the time is missing, use 23:59:00.
- course_name: pick one of the KNOWN COURSES when possible, otherwise null.
- title: short (max 8 words), in English. description: one sentence, in English.
- If there is no deadline: {"has_deadline": false, "course_name": null, "title": null, "description": null, "due_date": null}
"""

FEW_SHOT_USER = (
    "REFERENCE DATE: Monday 2026-03-02\nKNOWN COURSES: Statistics, Macroeconomics\n"
    "CHANNEL: Macroeconomics\nMESSAGE:\n\"Hi all, please upload exercise sheet 3 by Thursday at 2pm.\""
)
FEW_SHOT_ASSISTANT = json.dumps(
    {
        "has_deadline": True,
        "course_name": "Macroeconomics",
        "title": "Exercise sheet 3 submission",
        "description": "Upload of exercise sheet 3 requested by the lecturer.",
        "due_date": "2026-03-05T14:00:00",
    },
    ensure_ascii=False,
)


def _reference_label(ref: datetime) -> str:
    return f"{WEEKDAYS[ref.weekday()]} {ref.strftime('%Y-%m-%d')}"


def extract_deadline_from_text(
    text: str,
    known_courses: Optional[List[str]] = None,
    course_hint: Optional[str] = None,
    reference_date: Optional[datetime] = None,
) -> tuple[ExtractedDeadline, str]:
    """
    Estrae (se presente) una scadenza da un testo informale.

    Ritorna (ExtractedDeadline validato, output grezzo dell'LLM).
    Solleva LLMUnavailableError se Ollama non è raggiungibile,
    LLMParsingError se l'output non è JSON interpretabile.
    """
    ref = reference_date or settings.reference_now()
    user_prompt = (
        f"REFERENCE DATE: {_reference_label(ref)}\n"
        f"KNOWN COURSES: {', '.join(known_courses) if known_courses else 'none'}\n"
        f"CHANNEL: {course_hint or 'unknown'}\n"
        f"MESSAGE:\n\"{text.strip()}\""
    )
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": FEW_SHOT_USER},
        {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
        {"role": "user", "content": user_prompt},
    ]
    raw = _chat(messages, json_mode=True, temperature=0.0)
    data = parse_llm_json(raw)
    extraction = ExtractedDeadline.model_validate(data)
    if extraction.has_deadline and not _mentions_time(text):
        # Guard against hallucinated dates: a message with no time reference cannot contain a deadline
        logger.info("Estrazione scartata (nessun riferimento temporale nel testo): %s", extraction.model_dump())
        extraction = ExtractedDeadline.model_validate({"has_deadline": False})
    logger.info("Estrazione LLM: %s", extraction.model_dump())
    return extraction, raw


_TIME_WORDS = re.compile(
    r"\b\d{1,2}[:/.]\d{1,2}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}(st|nd|rd|th)\b|\b\d{1,2}\s*(am|pm)\b|"
    r"\b(in|within|tra|fra|entro)\s+\d+\s+(days?|weeks?|hours?|giorni|settimane|ore)\b|"
    r"\b(today|tonight|tomorrow|week|weekend|month|midnight|noon|morning|afternoon|evening|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|june|july|august|september|october|november|december|"
    r"jan|feb|apr|jun|jul|aug|sept?|oct|nov|dec|"
    r"oggi|stasera|domani|settimana|mese|mezzanotte|mezzogiorno|mattina|pomeriggio|sera|"
    r"luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|"
    r"gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\b",
    re.IGNORECASE,
)


def _mentions_time(text: str) -> bool:
    return bool(_TIME_WORDS.search(text or ""))


# ---------------------------------------------------------------------------
# Persistenza della scadenza estratta
# ---------------------------------------------------------------------------
def resolve_course(db: Session, course_name: Optional[str], fallback_code: Optional[str] = None) -> Optional[Course]:
    """
    Collega il nome di corso restituito dall'LLM a un Course in SQLite:
    match esatto su codice/nome -> sottostringa -> similarità fuzzy -> canale di provenienza.
    """
    courses = list(db.scalars(select(Course)))
    if course_name:
        name = course_name.strip().lower()
        for c in courses:
            if name in (c.name.lower(), c.code.lower()):
                return c
        for c in courses:
            if name in c.name.lower() or c.name.lower() in name:
                return c
        best, best_score = None, 0.0
        for c in courses:
            score = difflib.SequenceMatcher(None, name, c.name.lower()).ratio()
            if score > best_score:
                best, best_score = c, score
        if best and best_score >= 0.6:
            return best
    if fallback_code:
        return db.scalar(select(Course).where(Course.code == fallback_code))
    return None


_STOPWORDS = {
    "the", "a", "an", "of", "and", "for", "to", "on", "by", "in", "due", "deadline", "submission", "moved", "new",
    "di", "del", "della", "e", "la", "il", "lo", "le", "dei", "delle", "per", "consegna", "scadenza", "-",
}


def _find_superseded_moodle_deadline(db: Session, course: Optional[Course], extraction: ExtractedDeadline,
                                     message_time: Optional[datetime] = None) -> Optional[Deadline]:
    """
    Euristica demo: se nello stesso corso esiste una scadenza Moodle con titolo
    simile ma data diversa, l'avviso del docente probabilmente la sposta.
    """
    if course is None or not extraction.title:
        return None
    text_tokens = {t for t in re.findall(r"\w+", f"{extraction.title} {extraction.description or ''}".lower())} - _STOPWORDS
    candidates = db.scalars(
        select(Deadline).where(
            Deadline.course_id == course.id,
            Deadline.source == SourceType.MOODLE,
            Deadline.extracted_by_ai.is_(False),
        )
    )
    for d in candidates:
        tokens = set(re.findall(r"\w+", d.title.lower())) - _STOPWORDS
        # match anche su prefisso (es. "esercitazione" ~ "esercitazioni")
        overlap = any(a[:6] == b[:6] for a in tokens for b in text_tokens if len(a) > 3 and len(b) > 3)
        if overlap and d.due_date != extraction.due_date:
            if message_time and d.source_updated_at and message_time <= d.source_updated_at:
                continue   # the lecturer changed the official date after this message: the official date wins
            return d
    return None


def _newer_official_deadline(db: Session, course: Optional[Course], extraction: ExtractedDeadline,
                             message_time: Optional[datetime]) -> Optional[Deadline]:
    """A matching official (LMS) deadline changed *after* the message: the message's date is outdated."""
    if course is None or not extraction.title or message_time is None:
        return None
    text_tokens = {t for t in re.findall(r"\w+", f"{extraction.title} {extraction.description or ''}".lower())} - _STOPWORDS
    for d in db.scalars(select(Deadline).where(Deadline.course_id == course.id, Deadline.source == SourceType.MOODLE,
                                               Deadline.extracted_by_ai.is_(False), Deadline.source_updated_at.is_not(None))):
        tokens = set(re.findall(r"\w+", d.title.lower())) - _STOPWORDS
        if any(a[:6] == b[:6] for a in tokens for b in text_tokens if len(a) > 3 and len(b) > 3) and message_time <= d.source_updated_at:
            return d
    return None


def save_extracted_deadline(
    db: Session,
    extraction: ExtractedDeadline,
    source: SourceType,
    external_id: Optional[str] = None,
    fallback_course_code: Optional[str] = None,
    force_course_code: Optional[str] = None,
    announcement_id: Optional[int] = None,
) -> tuple[Optional[Deadline], Optional[Course], Optional[Dict[str, Any]]]:
    """
    Salva la scadenza estratta in SQLite (upsert su source+external_id).

    - `force_course_code`: corso certo (es. avviso pubblicato dal docente nel suo corso):
      ha la precedenza sul nome di corso proposto dall'LLM.
    - `announcement_id`: collega la scadenza all'avviso da cui è stata estratta.

    Ritorna (deadline salvata o None, corso associato, info su eventuale scadenza Moodle spostata).
    """
    if not extraction.has_deadline or extraction.due_date is None:
        # Se in precedenza lo stesso messaggio aveva generato una scadenza, la rimuoviamo
        if external_id:
            stale = db.scalar(select(Deadline).where(Deadline.source == source, Deadline.external_id == external_id))
            if stale is not None:
                for old in db.scalars(select(Deadline).where(Deadline.superseded_by_id == stale.id)):
                    old.superseded_by_id = None
                db.delete(stale)
                db.flush()
        return None, None, None

    if force_course_code:
        course = db.scalar(select(Course).where(Course.code == force_course_code))
    else:
        course = resolve_course(db, extraction.course_name, fallback_course_code)

    deadline = None
    if external_id:
        deadline = db.scalar(select(Deadline).where(Deadline.source == source, Deadline.external_id == external_id))
    if deadline is None:
        deadline = Deadline(source=source, external_id=external_id, extracted_by_ai=True)
        db.add(deadline)

    deadline.course_id = course.id if course else None
    deadline.title = extraction.title or "Extracted deadline"
    deadline.description = extraction.description
    deadline.due_date = extraction.due_date
    deadline.extracted_by_ai = True
    if announcement_id is not None:
        deadline.announcement_id = announcement_id
    db.flush()

    update_info = None
    message = db.get(Announcement, announcement_id) if announcement_id else None
    message_time = message.created_at if message else None
    newer = _newer_official_deadline(db, course, extraction, message_time)
    if newer is not None and newer.superseded_by_id != deadline.id:
        deadline.superseded_by_id = newer.id   # hide the outdated date found in the message
    superseded = _find_superseded_moodle_deadline(db, course, extraction, message_time)
    if superseded and deadline.superseded_by_id == superseded.id:
        superseded = None   # the lecturer set a newer official date in the LMS afterwards: that one wins
    if superseded:
        # La scadenza Moodle resta in DB (tracciabilità) ma viene nascosta dalle viste
        superseded.superseded_by_id = deadline.id
        update_info = {
            "moodle_deadline_id": superseded.id,
            "moodle_title": superseded.title,
            "old_due_date": superseded.due_date.isoformat(),
            "new_due_date": extraction.due_date.isoformat(),
        }
    _supersede_older_ai_duplicates(db, course, deadline)
    return deadline, course, update_info


def _title_tokens(text: str) -> set:
    return {t for t in re.findall(r"\w+", text.lower()) if len(t) > 3} - _STOPWORDS


def _supersede_older_ai_duplicates(db: Session, course: Optional[Course], deadline: Deadline) -> None:
    """
    Se nello stesso corso esistono scadenze AI simili estratte da avvisi *più vecchi*
    (es. il docente ripubblica o corregge l'avviso), vale l'ultimo avviso: le precedenti
    vengono nascoste. Il confronto per data dell'avviso evita che una nuova sync dei
    messaggi Teams storici nasconda un avviso più recente del docente.
    """
    if course is None or deadline.announcement is None:
        return
    current = deadline.announcement
    tokens = _title_tokens(deadline.title)
    others = db.scalars(
        select(Deadline).where(
            Deadline.course_id == course.id,
            Deadline.extracted_by_ai.is_(True),
            Deadline.id != deadline.id,
            Deadline.superseded_by_id.is_(None),
            Deadline.announcement_id.is_not(None),
        )
    )
    for other in others:
        ann = other.announcement
        older = (ann.created_at, ann.id) < (current.created_at, current.id)
        similar = any(a[:6] == b[:6] for a in _title_tokens(other.title) for b in tokens)
        if older and similar:
            other.superseded_by_id = deadline.id


def extract_and_save_deadline(
    db: Session,
    text: str,
    source: SourceType = SourceType.TEAMS,
    external_id: Optional[str] = None,
    fallback_course_code: Optional[str] = None,
    force_course_code: Optional[str] = None,
    announcement_id: Optional[int] = None,
) -> ExtractionResult:
    """Pipeline completa per un singolo messaggio: LLM -> parsing JSON -> SQLite."""
    known = [c.name for c in db.scalars(select(Course))]
    hint = None
    hint_code = force_course_code or fallback_course_code
    if hint_code:
        c = db.scalar(select(Course).where(Course.code == hint_code))
        hint = c.name if c else hint_code

    extraction, raw = extract_deadline_from_text(text, known_courses=known, course_hint=hint)
    deadline, course, update_info = save_extracted_deadline(
        db,
        extraction,
        source,
        external_id,
        fallback_course_code,
        force_course_code=force_course_code,
        announcement_id=announcement_id,
    )
    return ExtractionResult(
        extraction=extraction,
        raw_llm_output=raw,
        saved_deadline_id=deadline.id if deadline else None,
        matched_course_id=course.id if course else None,
        matched_course_name=course.name if course else None,
        updates_existing=update_info,
    )


# ---------------------------------------------------------------------------
# STEP 6 - Chatbot RAG
# ---------------------------------------------------------------------------
RAG_SYSTEM_PROMPT = (
    "You are the student's academic assistant. Answer the following question based "
    "exclusively on the provided context.\n"
    "Additional rules: answer in English (or in the language of the question if it is not English), "
    "concisely and in a friendly tone. If a lecturer announcement moves a deadline, the most recent "
    "date communicated by the lecturer is the valid one. If the information is not in the context, "
    "say so clearly without making anything up."
)


def _fmt_dt(dt: datetime) -> str:
    return f"{WEEKDAYS[dt.weekday()]} {dt.day} {dt.strftime('%B %Y')} at {dt.strftime('%H:%M')}"


def build_rag_context(db: Session, user_query: str, n_results: int = 4, user: Any = None) -> tuple[str, List[Dict[str, Any]]]:
    """Costruisce il contesto combinando SQLite (dati strutturati), ChromaDB (avvisi) e il riepilogo UniSIS."""
    now = settings.reference_now()
    user_id = getattr(user, "id", None)
    from app.services.my_courses import course_filter   # local import: keeps this module importable on its own
    own_deadline = (or_(Deadline.user_id.is_(None), Deadline.user_id == user_id)) & course_filter(db, user, Deadline.course_id)
    own_event = (or_(Event.user_id.is_(None), Event.user_id == user_id)) & course_filter(db, user, Event.course_id)
    sections: List[str] = [f"TODAY: {_fmt_dt(now)}"]
    sources: List[Dict[str, Any]] = []

    # 1) Scadenze future non completate (SQLite)
    deadlines = db.scalars(
        select(Deadline)
        .where(
            own_deadline,
            Deadline.is_completed.is_(False),
            ~Deadline.id.in_(select(DeadlineDone.deadline_id).where(DeadlineDone.user_id == user_id)),   # ticked by this student
            Deadline.superseded_by_id.is_(None),  # ignora le date poi spostate dal docente
            Deadline.due_date >= now.replace(hour=0, minute=0, second=0),
        )
        .order_by(Deadline.due_date)
        .limit(15)
    ).all()
    if deadlines:
        lines = []
        for d in deadlines:
            origin = f"{d.source.value}{', extracted by AI from a lecturer announcement' if d.extracted_by_ai else ''}"
            course = d.course.name if d.course else "no specific course"
            lines.append(f"- [{course}] {d.title}: {_fmt_dt(d.due_date)} (source: {origin})")
            sources.append({"type": "deadline", "id": d.id, "title": d.title})
        sections.append("UPCOMING DEADLINES:\n" + "\n".join(lines))

    # 2) Eventi in calendario (SQLite)
    events = db.scalars(select(Event).where(own_event, Event.start_time >= now).order_by(Event.start_time).limit(12)).all()
    if events:
        lines = [
            f"- [{e.course.name if e.course else '-'}] {e.title}: {_fmt_dt(e.start_time)} @ {e.location or 'n/a'}"
            for e in events
        ]
        sections.append("UPCOMING CLASSES AND EVENTS (timetable; an announcement may have cancelled some):\n" + "\n".join(lines))

    # 2b) UniSIS summary (credits, exam registrations, electives) if the student connected it
    if user_id is not None:
        conn = db.scalar(select(Connection).where(Connection.user_id == user_id, Connection.provider == "unisis"))
        if conn and conn.snapshot:
            try:
                snap = json.loads(conn.snapshot)
                lines = [
                    f"- Programme: {snap.get('programme')} (year {snap.get('year')})",
                    f"- Credits: {snap.get('credits_earned')}/{snap.get('credits_required')} ECTS earned, {snap.get('credits_in_progress')} in progress; weighted average {snap.get('weighted_average')} "
                    f"(Czech grading scale: 1 = excellent is the best grade, 4 = satisfactory is the lowest pass, 5 = fail; a lower average is better)",
                ]
                if snap.get("registered_exams"):
                    lines.append("- Registered exams: " + "; ".join(snap["registered_exams"]))
                if snap.get("exam_registration"):
                    lines.append("- Exam registration status: " + "; ".join(snap["exam_registration"]))
                el = snap.get("electives")
                if el:
                    lines.append(f"- Electives for the {el['term']} (registration {el['status']}, {el['required']} required): "
                                 f"chosen {', '.join(el['chosen']) or 'none'}; waiting list {', '.join(el['waitlisted']) or 'none'}")
                if snap.get("recent_grades"):
                    lines.append("- Recent grades: " + "; ".join(snap["recent_grades"]))
                sections.append("STUDENT RECORD (UniSIS):\n" + "\n".join(lines))
                sources.append({"type": "unisis", "id": conn.id})
            except ValueError:
                pass

    # 2c) Smart Notes (Premium): the student's lesson notes that match the question best
    if user_id is not None:
        from app.database.models import LessonNote   # local import: keeps this module importable on its own
        words = {w for w in re.findall(r"\w{4,}", user_query.lower())}
        notes = db.scalars(select(LessonNote).where(LessonNote.user_id == user_id, LessonNote.status == "ready")).all()
        scored = sorted(((len(words & set(re.findall(r"\w{4,}", f"{n.course_name} {n.lesson_name} {n.body_md}".lower()))), n) for n in notes),
                        key=lambda x: -x[0])
        picked = [n for score, n in scored[:2] if score > 0]
        if picked:
            sections.append("LESSON NOTES (made from the lecturers' slides, documents and recordings):\n" + "\n\n".join(
                f"[{n.course_name} · {n.lesson_name}]\n{n.body_md[:1800]}" for n in picked))
            sources += [{"type": "lesson_note", "id": n.id, "title": n.lesson_name} for n in picked]

    # 3) Avvisi semanticamente rilevanti (ChromaDB)
    try:
        hits = vector_store.query_relevant_context(user_query, n_results=n_results)
    except Exception as exc:  # il vector DB non deve mai bloccare la chat
        logger.warning("Ricerca vettoriale non disponibile: %s", exc)
        hits = []
    if hits:
        lines = []
        for h in hits:
            m = h["metadata"]
            lines.append(
                f"- ({m.get('source', '?')}, {m.get('course_name', '-')}, {m.get('author', '-')}, "
                f"{m.get('created_at', '')}): \"{h['text']}\""
            )
            sources.append({"type": "announcement", "id": h["id"], "distance": h["distance"]})
        sections.append("RELEVANT ANNOUNCEMENTS FROM LECTURERS AND OFFICES:\n" + "\n".join(lines))

    return "\n\n".join(sections), sources


def answer_student_query(user_query: str, db: Session, user: Any = None) -> Dict[str, Any]:
    """Risponde alla domanda dello studente con RAG su contesto locale."""
    context, sources = build_rag_context(db, user_query, user=user)
    messages = [
        {"role": "system", "content": RAG_SYSTEM_PROMPT},
        {"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {user_query}"},
    ]
    answer = _chat(messages, json_mode=False, temperature=0.2).strip()
    return {"answer": answer, "sources": sources, "context_used": context}
