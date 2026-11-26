"""
Writes the study notes of a lesson with the local llama3.2 (Ollama).

Short lessons: one request. Long ones (a one-hour transcript is about 50,000 characters): each part is
summarised on its own, then the parts are merged into one page. Output is JSON, turned into Markdown here.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.config import settings
from app.services.llm_extractor import LLMUnavailableError, chat_long, parse_llm_json

logger = logging.getLogger(__name__)

CHUNK_CHARS = 9000            # local AI (llama3.2 with NOTES_NUM_CTX 8192)
REMOTE_CHUNK_CHARS = 100000   # external AI (Gemini reads far longer texts): most lessons fit in one part
MAX_CHUNKS = 12
KIND_LABEL = {"pdf": "PDF", "slides": "slides", "document": "document", "text": "text", "audio": "audio recording", "video": "video recording"}


class NotesError(Exception):
    pass


SYSTEM = (
    "You write study notes for university students from the materials of one lesson "
    "(slides, documents and the transcript of the recorded lecture). "
    "Use only facts that are in the materials. Write in the same language as the materials. "
    "Be concrete: keep names, numbers, formulas and examples the lecturer gives. "
    "Reply with JSON only."
)

FULL_FORMAT = (
    'Return this JSON object:\n'
    '{"title": "short title of the lesson", '
    '"summary": "3 to 5 sentences: what the lesson covers and its main message", '
    '"key_points": ["6 to 12 points a student must remember, one sentence each"], '
    '"definitions": [{"term": "a term the lesson defines or uses as a technical word", "definition": "one or two sentences"}]}'
)

PART_FORMAT = (
    'This is one part of a longer lesson. Return this JSON object:\n'
    '{"summary": "2 or 3 sentences on this part", "key_points": ["up to 8 points"], '
    '"definitions": [{"term": "...", "definition": "..."}]}'
)


def _ask(prompt: str, should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    raw = chat_long([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                    {"temperature": 0.2, "num_ctx": settings.NOTES_NUM_CTX}, json_mode=True, should_stop=should_stop)
    try:
        data = parse_llm_json(raw)
    except Exception as exc:
        raise NotesError("The AI answer could not be read. Try Regenerate.") from exc
    return data if isinstance(data, dict) else {}


def _chunks(text: str) -> List[str]:
    from app.config import settings
    size = max(REMOTE_CHUNK_CHARS if settings.ai_remote else CHUNK_CHARS, len(text) // MAX_CHUNKS + 1)
    paras = re.split(r"\n\s*\n|\n(?=\[)", text)
    out, cur = [], ""
    for p in paras:
        while len(p) > size:   # a transcript has no paragraphs: cut at sentence ends
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 2 else size
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:cut])
            p = p[cut:].lstrip()
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}" if cur else p
    if cur.strip():
        out.append(cur)
    return out


def _str_list(v: Any, limit: int) -> List[str]:
    items = v if isinstance(v, list) else []
    out: List[str] = []
    for x in items:
        if isinstance(x, dict):
            x = x.get("point") or x.get("text") or ""
        s = str(x).strip(" -•\n")
        if s and s.lower() not in {o.lower() for o in out}:
            out.append(s)
    return out[:limit]


def _defs(v: Any, limit: int) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    seen = set()
    for d in v if isinstance(v, list) else []:
        if not isinstance(d, dict):
            continue
        term, definition = str(d.get("term") or "").strip(), str(d.get("definition") or "").strip()
        if term and definition and term.lower() not in seen:
            seen.add(term.lower())
            out.append({"term": term, "definition": definition})
    return out[:limit]


def generate(course_name: str, lesson_name: str, sources: Sequence[Tuple[str, str, str]],
             should_stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """sources: (filename, kind, text). Returns title, summary, key_points, definitions. should_stop: see chat_long."""
    blocks = [f"### SOURCE: {name} ({KIND_LABEL.get(kind, kind)})\n{text.strip()}" for name, kind, text in sources if text and text.strip()]
    if not blocks:
        raise NotesError("No readable text in the files of this lesson (a scanned PDF or a silent recording?).")
    material = "\n\n".join(blocks)
    header = f"COURSE: {course_name}\nLESSON: {lesson_name}\n\n"
    chunks = _chunks(material)
    logger.info("Smart Notes: %s / %s, %d characters, %d part(s)", course_name, lesson_name, len(material), len(chunks))
    if len(chunks) == 1:
        data = _ask(f"{header}MATERIALS:\n{material}\n\n{FULL_FORMAT}", should_stop)
    else:
        parts = []
        for i, c in enumerate(chunks, 1):
            p = _ask(f"{header}PART {i} OF {len(chunks)}:\n{c}\n\n{PART_FORMAT}", should_stop)
            parts.append({"summary": str(p.get("summary") or ""), "key_points": _str_list(p.get("key_points"), 8),
                          "definitions": _defs(p.get("definitions"), 8)})
        merged_input = json.dumps(parts, ensure_ascii=False)
        try:
            data = _ask(f"{header}These are notes on the parts of the lesson, in order:\n{merged_input}\n\n"
                        f"Merge them into one page of notes for the whole lesson. {FULL_FORMAT}", should_stop)
        except NotesError:
            data = {}
        # keep the definitions of every part even if the merge drops some
        data["definitions"] = (data.get("definitions") or []) + [d for p in parts for d in p["definitions"]]
        if not data.get("key_points"):
            data["key_points"] = [k for p in parts for k in p["key_points"]]
        if not data.get("summary"):
            data["summary"] = " ".join(p["summary"] for p in parts[:3])
    result = {
        "title": str(data.get("title") or lesson_name).strip() or lesson_name,
        "summary": str(data.get("summary") or "").strip(),
        "key_points": _str_list(data.get("key_points"), 14),
        "definitions": _defs(data.get("definitions"), 14),
    }
    if not result["summary"] and not result["key_points"]:
        raise NotesError("The AI returned empty notes. Try Regenerate.")
    return result


def to_markdown(notes: Dict[str, Any], course_name: str, lesson_name: str, sources: Sequence[Tuple[str, str]]) -> str:
    lines = [f"# {notes['title']}", "", f"*{course_name} · {lesson_name}*", ""]
    if notes["summary"]:
        lines += ["## Summary", "", notes["summary"], ""]
    if notes["key_points"]:
        lines += ["## Key points", ""] + [f"- {k}" for k in notes["key_points"]] + [""]
    if notes["definitions"]:
        lines += ["## Definitions", ""] + [f"- **{d['term']}**: {d['definition']}" for d in notes["definitions"]] + [""]
    if sources:
        lines += ["## Sources", ""] + [f"- {name} ({KIND_LABEL.get(kind, kind)})" for name, kind in sources] + [""]
    return "\n".join(lines).strip() + "\n"
