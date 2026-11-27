"""
Exam dates in the text of one course file. Rule number one: no date at all is better than a wrong date.

1. Pre-filter, no AI: only the lines with a written date AND an exam word near it go to the AI (often none: no AI call).
2. The AI returns each date with the sentence copied word for word from the file and the page.
3. Checks in code (dates.py is the judge). A proposal is thrown away when:
   - the quote is not in the file (on any page);
   - our own reading of the quote does not give the same day and month as the AI;
   - no word of that kind of event (exam, midterm, test, presentation, submission) is in the quote or right next to it;
   - the date is in the past or outside the academic year.
   A time or a room the AI gives that is not written in the quote is dropped (the date stays, "time not stated").
4. A second, independent question to the AI: "Does this text say there is <event> on <date>? yes/no". Only "yes" stays.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.exam_dates.dates import academic_year_bounds, complete_year, find_dates, find_times, fold

logger = logging.getLogger(__name__)
VERSION = "1"            # bump to read every file again after a change of the rules
BATCH_CHARS = 7000

KIND_WORDS: Dict[str, Tuple[str, ...]] = {
    "midterm": ("midterm", "mid-term", "mid term", "interim exam", "interim test", "prubezn", "zapoctov"),
    "exam": ("final exam", "exam", "examination", "final test", "zkousk", "zkouska", "esame", "appello", "resit", "re-sit", "retake"),
    "test": ("test", "quiz", "written", "pisemk", "prova", "verifica", "kviz"),
    "presentation": ("presentation", "present ", "presenting", "pitch", "defence", "defense", "prezentac", "presentazion", "obhajob"),
    "submission": ("deadline", "due", "submit", "submission", "hand in", "hand-in", "upload", "odevzd", "consegn", "scadenz",
                   "essay", "report", "assignment", "project", "paper", "seminar work", "seminarni prace"),
}
ALL_WORDS = tuple(w for words in KIND_WORDS.values() for w in words)
KIND_LABEL = {"exam": "Final exam", "midterm": "Midterm", "test": "Test", "presentation": "Presentation", "submission": "Submission"}
PAGE_RE = re.compile(r"^\[(Page|Slide) (\d+)\]\s*$", re.M)

SYSTEM = (
    "You find exam dates in university course documents (syllabi, first-lesson slides). "
    "You never guess: a date that is not written explicitly in the text is not returned. "
    "Answer only with JSON."
)
PROMPT = """Below are excerpts of the course file "{filename}" ({course}). Each excerpt starts with its page.

Return every date when students have a FINAL EXAM, MIDTERM, TEST or QUIZ, a PRESENTATION or DEFENCE, or must SUBMIT work (essay, project, report, assignment).
Rules:
- Only dates written explicitly with day and month (e.g. "16.12.", "3 November", "16. prosince"). Not "week 12", not "end of semester", not "TBA".
- Not lecture or seminar dates, holidays, the start or end of the exam period, or registration windows.
- "quote": copy word for word the sentence or table row of the excerpt that contains BOTH the date and what happens. Do not change, translate or shorten words inside it.
- "date": YYYY-MM-DD. If the year is not written, use the year that makes sense for the academic year {year_start}/{year_end}.
- "time": "HH:MM" only if written next to the date, else null. "room": only if written, else null.
- "kind": one of "exam", "midterm", "test", "presentation", "submission".
- "title": short name of the event as written (e.g. "Mid-term progress report", "Final exam").
- If there is no such date, return {{"items": []}}.

JSON format:
{{"items": [{{"kind": "...", "title": "...", "date": "YYYY-MM-DD", "time": null, "room": null, "page": "Page 4", "quote": "..."}}]}}

EXCERPTS:
{excerpts}"""

CHECK_PROMPT = """Text from the course file "{filename}":
\"\"\"{context}\"\"\"

Question: according to this text, is "{written}" (day {day}, month {month}) the date of this event: {kind_label} "{title}"?
- The text may not write the year or the weekday: that is fine, judge only the day and the month.
- Answer "yes" if the text links this date to this event (same sentence, or same row of a table).
- Answer "no" if the date belongs to something else (an ordinary lecture, a registration window, a holiday, another event) or if it is unclear.
Reply only with JSON: {{"answer": "yes"}} or {{"answer": "no"}}"""


@dataclass
class Page:
    label: str        # "Page 4", "Slide 3" or ""
    text: str
    folded: str = field(init=False)

    def __post_init__(self) -> None:
        self.folded = fold(self.text)


@dataclass
class Found:
    kind: str
    title: str
    on_date: date
    at_time: Optional[str]
    room: Optional[str]
    page: str
    quote: str
    year_written: bool


def split_pages(text: str) -> List[Page]:
    marks = list(PAGE_RE.finditer(text))
    if not marks:
        return [Page("", text)]
    pages = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        pages.append(Page(f"{m.group(1)} {m.group(2)}", text[m.end():end].strip()))
    return pages


def _has_word(folded: str, words: Tuple[str, ...]) -> bool:
    return any(re.search(r"(?<![a-z])" + re.escape(w), folded) for w in words)


def excerpts(pages: List[Page], before: int = 2, after: int = 2) -> List[Tuple[str, str]]:
    """(page label, lines) around every line with a date that has an exam word within the excerpt. No AI."""
    out: List[Tuple[str, str]] = []
    for p in pages:
        lines = [ln for ln in p.text.splitlines()]
        keep = set()
        for i, ln in enumerate(lines):
            if not find_dates(ln):
                continue
            lo, hi = max(0, i - before), min(len(lines), i + after + 1)
            if _has_word(fold(" ".join(lines[lo:hi])), ALL_WORDS):
                keep.update(range(lo, hi))
        if not keep:
            continue
        block: List[str] = []
        last = None
        for i in sorted(keep):
            if last is not None and i != last + 1:
                out.append((p.label, "\n".join(block)))
                block = []
            block.append(lines[i])
            last = i
        if block:
            out.append((p.label, "\n".join(block)))
    return out


def _batches(parts: List[Tuple[str, str]]) -> List[str]:
    batches, cur = [], ""
    for label, txt in parts:
        piece = f"--- {label or 'Text'} ---\n{txt}\n"
        if cur and len(cur) + len(piece) > BATCH_CHARS:
            batches.append(cur)
            cur = ""
        cur += piece
    if cur:
        batches.append(cur)
    return batches


def _locate(quote: str, pages: List[Page], hint: str) -> Optional[Tuple[Page, int]]:
    """The page that contains the quote word for word (folded), the hinted page first."""
    q = fold(quote).strip(" .,;:\"'")
    if len(q) < 8:
        return None
    for p in sorted(pages, key=lambda p: p.label != hint):
        pos = p.folded.find(q)
        if pos >= 0:
            return p, pos
    return None


def _heading_above(page: Page, quote: str) -> str:
    """The non-empty line just above the quote, if it looks like a heading: short, no date (folded; "" otherwise)."""
    lines = [fold(ln) for ln in page.text.splitlines()]
    q = fold(quote)
    for i, ln in enumerate(lines):
        if ln and (q.startswith(ln[:30]) or ln.startswith(q[:30])):
            for prev in reversed(lines[:i]):
                if prev:
                    return prev if len(prev) <= 60 and not find_dates(prev, folded=True) else ""
            return ""
    return ""


def verify(item: Dict[str, Any], pages: List[Page], today: date) -> Tuple[Optional[Found], str]:
    """Checks one AI proposal against the file. Returns (Found, "") or (None, why it was thrown away)."""
    quote = str(item.get("quote") or "").strip()
    if not quote or len(quote) > 600:
        return None, "no quote"
    where = _locate(quote, pages, str(item.get("page") or ""))
    if where is None:
        return None, "quote not in the file"
    page, pos = where
    try:
        ai_date = date.fromisoformat(str(item.get("date") or "")[:10])
    except ValueError:
        return None, "no date"
    written = [d for d in find_dates(quote) if d.day == ai_date.day and d.month == ai_date.month]
    if not written:
        return None, "the date is not written in the quote"
    w = written[0]
    if w.year is not None:
        on = date(w.year, w.month, w.day)
    else:
        try:
            on = complete_year(w.day, w.month, today)
        except ValueError:
            return None, "impossible date"
    start, end = academic_year_bounds(today)
    if not (start <= on <= end):
        return None, "outside the academic year"
    if on < today:
        return None, "in the past"
    # the kind must be written in the quote itself, or in a heading right above it with no date ("Exam dates:").
    # Words in the neighbouring rows of a table do not count: "25.11 Strategy 2" next to "18.11 MID TERM EXAM" is a lecture.
    q = fold(quote)
    near = page.folded[max(0, pos - 160): pos + len(q) + 160]
    heading = _heading_above(page, quote)
    kind = str(item.get("kind") or "").lower()
    if kind not in KIND_WORDS or not (_has_word(q, KIND_WORDS[kind]) or _has_word(heading, KIND_WORDS[kind])):
        kind = next((k for k, words in KIND_WORDS.items() if _has_word(q, words)), "") or \
            next((k for k, words in KIND_WORDS.items() if _has_word(heading, words)), "")
        if not kind:
            return None, "no exam word next to the date"
    if kind == "exam" and _has_word(q, KIND_WORDS["midterm"]):
        kind = "midterm"   # "MID TERM EXAM" is a midterm, not the final exam
    at_time = None
    if item.get("time"):
        try:
            t = datetime.strptime(str(item["time"])[:5], "%H:%M").time()
            at_time = t.strftime("%H:%M") if t in find_times(quote) else None
        except ValueError:
            at_time = None
    room = str(item.get("room") or "").strip() or None
    if room and fold(room) not in near:
        room = None
    title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:120] or KIND_LABEL[kind]
    return Found(kind, title, on, at_time, room, page.label, quote, w.year is not None), ""


def _context(found: Found, pages: List[Page]) -> str:
    where = _locate(found.quote, pages, found.page)
    if where is None:
        return found.quote
    page, pos = where
    # original text around the quote: the lines that contain it plus one line before and after
    lines = page.text.splitlines()
    q = fold(found.quote)
    hits = [i for i, ln in enumerate(lines) if fold(ln) and fold(ln) in q or q[:40] in fold(ln)]
    if not hits:
        return found.quote
    lo, hi = max(0, min(hits) - 1), min(len(lines), max(hits) + 2)
    return "\n".join(lines[lo:hi])


def find_in_file(text: str, filename: str, course: str, today: date,
                 ask: Callable[[List[Dict[str, str]], bool], str],
                 parse: Callable[[str], Any], double_check: bool = True) -> Tuple[List[Found], int, int]:
    """
    All the exam dates of one file. ask(messages, fast) -> AI answer (JSON text); parse = robust JSON parser.
    Returns (dates that passed every check, proposals thrown away, AI calls made).
    """
    pages = split_pages(text)
    parts = excerpts(pages)
    if not parts:
        return [], 0, 0
    start, end = academic_year_bounds(today)
    found: List[Found] = []
    thrown, calls = 0, 0
    for batch in _batches(parts):
        prompt = PROMPT.format(filename=filename, course=course, year_start=start.year, year_end=end.year, excerpts=batch)
        raw = ask([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}], False)
        calls += 1
        try:
            data = parse(raw)
        except Exception:
            logger.warning("Exam dates: unreadable AI answer for %s: %r", filename, raw[-200:])
            continue
        items = data.get("items") if isinstance(data, dict) else data if isinstance(data, list) else []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            f, why = verify(item, pages, today)
            if f is None:
                thrown += 1
                logger.info("Exam dates: thrown away in %s (%s): %r %r", filename, why, item.get("date"), str(item.get("quote"))[:120])
                continue
            if any(x.kind == f.kind and x.on_date == f.on_date and fold(x.title) == fold(f.title) for x in found):
                continue
            found.append(f)
    if double_check:
        kept = []
        for f in found:
            written = next((d.text for d in find_dates(f.quote) if d.day == f.on_date.day and d.month == f.on_date.month), "")
            prompt = CHECK_PROMPT.format(filename=filename, context=_context(f, pages)[:1500], kind_label=KIND_LABEL[f.kind].lower(),
                                         title=f.title, written=written, day=f.on_date.day, month=f.on_date.strftime("%B"))
            raw = ask([{"role": "user", "content": prompt}], True)
            calls += 1
            try:
                answer = str(parse(raw).get("answer", "")).strip().lower()
            except Exception:
                answer = ""
            if answer == "yes":
                kept.append(f)
            else:
                thrown += 1
                logger.info("Exam dates: second check said %r for %s %s in %s", answer or "?", f.title, f.on_date, filename)
        found = kept
    return found, thrown, calls
