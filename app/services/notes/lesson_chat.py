"""
Chat on the uploaded material only: questions about one lesson, or one file of it.

Retrieval (RAG) over the text read from the lesson files (slides, documents, transcripts):
  1. the text is cut into short pieces that keep their place: "Slide 3", "Page 2", "12:30" in a recording
  2. pieces are ranked twice, by meaning (ChromaDB embeddings, collection "lesson_chunks") and by shared words
     (useful for names, numbers and non-English text); the two rankings are merged (reciprocal rank fusion)
  3. llama3.2 answers only from the best pieces and cites them as [1], [2]...
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ollama

from app.config import settings
from app.services.llm_extractor import LLMUnavailableError, get_ollama_client

logger = logging.getLogger(__name__)

PIECE_CHARS = 1100
CONTEXT_CHARS = 6500
MAX_PIECES = 8
COLLECTION = "lesson_chunks"
MARKER = re.compile(r"^\[(?:(Slide|Page) (\d+)|(\d{1,2}:\d{2}(?::\d{2})?))\]\s*$")

SYSTEM = (
    "You help a university student study the files of one lesson. "
    "Answer ONLY with what is written in the EXCERPTS. Do not use outside knowledge, even if you know the topic. "
    "If the excerpts do not contain the answer, say clearly that the uploaded material does not cover it, "
    "and say what the material does talk about. "
    "Answer in the same language as the question, in a few sentences or a short list. "
    "After each fact, cite the excerpt number in square brackets, for example [2]."
)


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


def _keyword_rank(question: str, pieces: Sequence[Piece]) -> List[int]:
    q = set(_words(question))
    if not q:
        return []
    docs = [Counter(_words(p["text"] + " " + p["label"])) for p in pieces]
    n = len(docs)
    df = Counter(w for d in docs for w in set(d) if w in q)
    scored = []
    for i, d in enumerate(docs):
        s = sum((1 + math.log(d[w])) * math.log(1 + n / df[w]) for w in q if d.get(w))
        if s > 0:
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
    return sorted(picked, key=lambda p: (p["filename"], int(p["key"].rsplit(":", 1)[1])))   # reading order


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
    excerpts = "\n\n".join(f"[{n}] {p['filename']}{' · ' + p['label'] if p['label'] else ''}\n{p['text']}" for n, p in enumerate(found, 1))
    messages = [{"role": "system", "content": SYSTEM}]
    for t in history[-6:]:
        if t.get("role") in ("user", "assistant") and t.get("content"):
            messages.append({"role": t["role"], "content": str(t["content"])[:1500]})
    messages.append({"role": "user", "content": f"MATERIAL: {scope_label}\n\nEXCERPTS:\n{excerpts}\n\nQUESTION: {question}"})
    try:
        res = get_ollama_client().chat(model=settings.OLLAMA_MODEL, messages=messages,
                                       options={"temperature": 0.1, "num_ctx": settings.NOTES_NUM_CTX})
        text = (res["message"]["content"] or "").strip()
    except ollama.ResponseError as exc:
        raise LLMUnavailableError(f"Ollama returned an error ({exc.status_code}): {exc.error}") from exc
    except Exception as exc:
        raise LLMUnavailableError(f"The local AI is not running (Ollama at {settings.OLLAMA_HOST}): {exc}") from exc
    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", text)}
    sources = [{"n": n, "filename": p["filename"], "kind": p["kind"], "label": p["label"], "excerpt": p["text"][:240]}
               for n, p in enumerate(found, 1) if not cited or n in cited]
    return {"answer": text, "sources": sources}

