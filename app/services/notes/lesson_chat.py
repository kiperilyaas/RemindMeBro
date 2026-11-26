"""
Chat on the uploaded material only: questions about one lesson, or one file of it.

Retrieval (RAG) over the text read from the lesson files (slides, documents, transcripts):
  1. the text is cut into short pieces that keep their place: "Slide 3", "Page 2", "12:30" in a recording
  2. pieces are ranked twice, by meaning (ChromaDB embeddings, collection "lesson_chunks") and by shared words
     (useful for names, numbers and non-English text); the two rankings are merged (reciprocal rank fusion)
  3. llama3.2 answers only from the best pieces (most relevant first) and cites them as [1], [2]...
  4. the answer is checked against the pieces: a citation that points to a piece without the dates or numbers it
     claims is moved to the piece that has them (or dropped), and page numbers the model wrote itself are removed,
     since the app shows the page next to each citation
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.config import settings
from app.services.llm_extractor import LLMUnavailableError, chat_long

logger = logging.getLogger(__name__)

PIECE_CHARS = 1100
CONTEXT_CHARS = 5500
MAX_PIECES = 6
COLLECTION = "lesson_chunks"
MARKER = re.compile(r"^\[(?:(Slide|Page) (\d+)|(\d{1,2}:\d{2}(?::\d{2})?))\]\s*$")

SYSTEM = """You help a university student with the files of one lesson.
Rules:
- Use ONLY the SOURCES below. No outside knowledge, even if you know the topic.
- Start with the direct answer in one sentence. Write the key fact (date, number, name) in **bold**, exactly as the source writes it.
- After each fact, write the number of its source in square brackets, like [1]. Use only numbers from the SOURCES list. Never write file names or page numbers yourself: the app shows them.
- Keep it short: one to four sentences, or a short list with "- " when there are several items.
- If the SOURCES do not answer the question, say that the material does not say it, then say in one sentence what the material covers.
- Answer in the same language as the question.
The SOURCES are ordered by relevance: [1] is the most likely to contain the answer."""


class LessonChatError(Exception):
    pass


Piece = Dict[str, Any]   # {key, contenthash, filename, kind, label, text}


def split_pieces(text: str) -> List[Tuple[str, str]]:
    """(label, text) pieces of a file. The label is where the piece is: 'Slide 3', 'Page 2', '12:30' or ''."""
    sections: List[Tuple[str, List[str]]] = [("", [])]
    for line in text.replace("\r\n", "\n").split("\n"):
        m = MARKER.match(line.strip())
        if m:
            label = f"{m.group(1)} {m.group(2)}" if m.group(1) else m.group(3)
            sections.append((label, []))
        else:
            sections[-1][1].append(line)
    out: List[Tuple[str, str]] = []
    for label, lines in sections:
        body = re.sub(r"[ \t]+", " ", "\n".join(lines)).strip()
        while len(body) > PIECE_CHARS:
            cut = max(body.rfind(". ", 0, PIECE_CHARS), body.rfind("\n", 0, PIECE_CHARS))
            cut = cut + 1 if cut > PIECE_CHARS // 2 else PIECE_CHARS
            out.append((label, body[:cut].strip()))
            body = body[cut:].strip()
        if body:
            out.append((label, body))
    return out


# common words in the languages of the demo (English, Italian, Czech) carry no meaning for the search
STOP = set("""the and for are was were with from that this what which who whom when where why how does did has have had
not but you your can could would should about into than then them they their there these those will shall also its
che con per non una uno del della delle dei degli nel nella sono come cosa quale quali quando dove perche anche alla
alle allo agli dal dalla questo questa questi quelle quello sul sulla piu molto essere stato stata hanno
jak jake jaky kdy kde proc ale pro nebo jsou byl byla bylo tak tento tato toto ktery ktera ktere""".split())


def _words(text: str) -> List[str]:
    plain = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()
    return [w[:6] for w in re.findall(r"[a-z0-9]{3,}", plain) if w not in STOP]   # first 6 letters: a cheap stem for any language


DATE = re.compile(r"\b\d{1,2}\s*[./]\s*\d{1,2}\b|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|gen|mag|giu|lug|ago|set|ott|dic)", re.I)
WHEN = re.compile(r"\b(when|date|deadline|due|quando|scadenza|entro|kdy|termin|datum)\b", re.I)


def _keyword_rank(question: str, pieces: Sequence[Piece]) -> List[int]:
    qw = _words(question)
    q = set(qw)
    if not q:
        return []
    pairs = {(a, b) for a, b in zip(qw, qw[1:])}   # "mid term", "progress report": words side by side count more
    seqs = [_words(p["text"] + " " + p["label"]) for p in pieces]
    docs = [Counter(w) for w in seqs]
    n = len(docs)
    df = Counter(w for d in docs for w in set(d) if w in q)
    asks_when = bool(WHEN.search(question))
    scored = []
    for i, d in enumerate(docs):
        s = sum((1 + math.log(d[w])) * math.log(1 + n / df[w]) for w in q if d.get(w))
        if s <= 0:
            continue
        s += 1.5 * len(pairs & set(zip(seqs[i], seqs[i][1:])))
        if asks_when and DATE.search(pieces[i]["text"]):
            s *= 1.3
        scored.append((s, i))
    return [i for _, i in sorted(scored, reverse=True)]


def _collection():
    from app.services import vector_store
    vector_store.get_collection()   # builds the shared client
    return vector_store._client.get_or_create_collection(name=COLLECTION, metadata={"hnsw:space": "cosine"})


def _embedding_rank(question: str, pieces: Sequence[Piece]) -> List[int]:
    try:
        col = _collection()
        hashes = sorted({p["contenthash"] for p in pieces})
        for h in hashes:   # index each file once (shared by every student)
            if not col.get(ids=[f"{h}:0"])["ids"]:
                mine = [p for p in pieces if p["contenthash"] == h]
                col.upsert(ids=[p["key"] for p in mine], documents=[p["text"] for p in mine],
                           metadatas=[{"contenthash": h, "label": p["label"]} for p in mine])
        where = {"contenthash": hashes[0]} if len(hashes) == 1 else {"contenthash": {"$in": hashes}}
        res = col.query(query_texts=[question], n_results=min(16, len(pieces)), where=where)
        index = {p["key"]: i for i, p in enumerate(pieces)}
        return [index[k] for k in res["ids"][0] if k in index]
    except Exception as exc:   # the vector store must never stop the chat: words alone still work
        logger.warning("Lesson chat: embedding search not available (%s)", exc)
        return []


def retrieve(question: str, pieces: Sequence[Piece]) -> List[Piece]:
    ranks = [_embedding_rank(question, pieces), _keyword_rank(question, pieces)]
    score: Dict[int, float] = {}
    for rank in ranks:
        for pos, i in enumerate(rank):
            score[i] = score.get(i, 0.0) + 1.0 / (60 + pos)
    order = sorted(score, key=lambda i: -score[i]) or list(range(len(pieces)))   # nothing matched: start of the files
    picked, used = [], 0
    for i in order:
        p = pieces[i]
        if len(picked) >= MAX_PIECES or (picked and used + len(p["text"]) > CONTEXT_CHARS):
            break
        picked.append(p)
        used += len(p["text"])
    return picked   # most relevant first: the small model reads [1] best


def answer(question: str, files: Sequence[Tuple[str, str, str, str]], history: Sequence[Dict[str, str]],
           scope_label: str) -> Dict[str, Any]:
    """files: (contenthash, filename, kind, text). history: earlier turns [{role, content}]."""
    pieces: List[Piece] = []
    for h, name, kind, text in files:
        for i, (label, body) in enumerate(split_pieces(text)):
            pieces.append({"key": f"{h}:{i}", "contenthash": h, "filename": name, "kind": kind, "label": label, "text": body})
    if not pieces:
        raise LessonChatError("There is no readable text in this material yet.")
    last_user = next((t["content"] for t in reversed(history) if t.get("role") == "user"), "")
    found = retrieve(f"{question} {last_user}".strip(), pieces)
    excerpts = "\n\n".join(f"SOURCE [{n}]{' (' + p['label'] + ')' if p['label'] else ''}\n{p['text']}" for n, p in enumerate(found, 1))
    messages = [{"role": "system", "content": SYSTEM}]
    for t in history[-6:]:
        if t.get("role") in ("user", "assistant") and t.get("content"):
            # old answers cite old source numbers: without them the model does not mix them up with the new SOURCES
            messages.append({"role": t["role"], "content": CITE.sub("", str(t["content"]))[:1500].strip()})
    messages.append({"role": "user", "content": f"MATERIAL: {scope_label}\n\nSOURCES:\n{excerpts}\n\nQUESTION: {question}"})
    text = chat_long(messages, {"temperature": 0.1, "num_ctx": settings.NOTES_NUM_CTX}).strip()
    text, used = check_citations(text, found, [p["filename"] for p in pieces])
    sources = [{"n": n, "filename": found[n - 1]["filename"], "kind": found[n - 1]["kind"], "label": found[n - 1]["label"],
                "excerpt": snippet(found[n - 1]["text"], claim)} for n, claim in used]
    return {"answer": text, "sources": sources}


# ---------------------------------------------------------------------------
# Checking the answer against the sources
# ---------------------------------------------------------------------------
CITE = re.compile(r"\s*\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]")
NUM = re.compile(r"\d+(?:[./:]\d+)*")
PAGE_TALK = re.compile(r"\s*\(?\b(?:on |at |see |from |in )?(?:page|slide|pagina|p\.)\s*\d+\b\)?", re.I)
# a sentence ends at . ! ? followed by a capital letter / list item, or at a new line ("3.11. " inside a sentence is a date)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z*\-\u00C0-\u017D])|\n+")


def _nums(text: str) -> set:
    """'3.11.' and '03.11' are the same date; '12:30' stays a time."""
    return {".".join(str(int(x)) for x in re.split(r"[./:]", m) if x) for m in NUM.findall(text)}


def _support(claim: str, piece: Piece) -> Tuple[int, int]:
    """(how many numbers of the claim are in the piece, how many words) -- numbers decide first."""
    return len(_nums(claim) & _nums(piece["text"])), len(set(_words(claim)) & set(_words(piece["text"])))


def _resolve(sentence: str, cited: List[int], found: Sequence[Piece]) -> List[int]:
    nums = _nums(sentence)
    ok = [n for n in cited if 1 <= n <= len(found) and
          (_support(sentence, found[n - 1])[0] == len(nums) if nums else _support(sentence, found[n - 1])[1] > 0)]
    if ok:
        return ok
    if not cited and not nums:
        return []   # a sentence without facts and without citation stays as it is
    (num_hit, word_hit), n = max((_support(sentence, p), i + 1) for i, p in enumerate(found))
    if (nums and num_hit == len(nums)) or (not nums and word_hit >= 2):
        return [n]
    return []   # nothing in the sources backs it: no citation, rather than a wrong page


def check_citations(text: str, found: Sequence[Piece], filenames: Sequence[str]) -> Tuple[str, List[Tuple[int, str]]]:
    """
    Each sentence gets the source that really holds its dates and numbers, at its end: a wrong or invented number
    is moved or dropped. File names and page numbers the model wrote itself are removed (the app shows them).
    """
    for name in sorted({f for f in filenames if len(f) >= 5 and "." in f}, key=len, reverse=True):   # "file.pdf · Page 11"
        text = re.sub(r"\s*" + re.escape(name) + r"\s*(?:·|,|-)?\s*(?:(?:Page|Slide)\s*\d+)?", " ", text)
    text = PAGE_TALK.sub("", text)
    used: Dict[int, str] = {}
    out_lines = []
    for line in text.split("\n"):
        parts = SENTENCE.split(line)
        fixed_parts = []
        for sent in parts:
            cited = [int(x) for g in CITE.findall(sent) for x in re.split(r"\s*,\s*", g)]
            plain = CITE.sub("", sent).rstrip()
            plain = re.sub(r"[ \t]{2,}", " ", re.sub(r"[ \t]+([.,;:])", r"\1", plain))
            plain = re.sub(r",\s*,", ",", plain).replace(" ,", ",")
            plain = re.sub(r"\b(on|by|at|is|was|il|entro|dne)\s*,\s*", r"\1 ", plain)   # "due on, 3.11" after removing a file name
            refs = _resolve(plain, cited, found) if plain.strip() else []
            if not refs and _nums(plain) and not any(_support(plain, p)[0] == len(_nums(plain)) for p in found):
                plain = re.sub(r"([.!?])?$", r" (not found in the material)\1", plain, count=1)   # a date or number no source has
            for n in refs:
                used.setdefault(n, plain)
            if refs:
                tag = " " + "".join(f"[{n}]" for n in refs)
                m = re.search(r"([.!?:;])$", plain)
                plain = plain[:m.start()] + tag + m.group(1) if m else plain + tag
            fixed_parts.append(plain)
        out_lines.append(" ".join(p for p in fixed_parts if p.strip()) if parts else line)
    fixed = "\n".join(out_lines).strip()
    return fixed, sorted(used.items())


def snippet(text: str, claim: str, size: int = 260) -> str:
    """The part of the source that holds the cited fact (its dates/numbers or words), not just the start of the page."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if not lines:
        return ""
    nums, words = _nums(claim), set(_words(claim))
    best = max(range(len(lines)), key=lambda i: (len(nums & _nums(lines[i])), len(words & set(_words(lines[i])))))
    out, i = lines[best], best
    lo, hi = best - 1, best + 1
    while len(out) < size and (lo >= 0 or hi < len(lines)):   # add the lines around it
        if lo >= 0:
            out = lines[lo] + " · " + out
            lo -= 1
        if hi < len(lines) and len(out) < size:
            out = out + " · " + lines[hi]
            hi += 1
    return out if len(out) <= size + 80 else out[: size + 80].rsplit(" ", 1)[0] + "…"

