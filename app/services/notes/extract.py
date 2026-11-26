"""Reads the text of a course file: PDF, PowerPoint, Word, plain text. Audio and video go to transcribe.py."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

KIND_BY_EXT = {
    ".pdf": "pdf", ".pptx": "slides", ".docx": "document", ".txt": "text", ".md": "text",
    ".mp3": "audio", ".m4a": "audio", ".wav": "audio", ".ogg": "audio", ".aac": "audio", ".flac": "audio",
    ".mp4": "video", ".mov": "video", ".webm": "video", ".mkv": "video", ".m4v": "video",
}
MEDIA_KINDS = {"audio", "video"}


class ExtractError(Exception):
    pass


def kind_of(filename: str, mimetype: str = "") -> Optional[str]:
    """pdf | slides | document | text | audio | video, or None for files Smart Notes cannot read."""
    kind = KIND_BY_EXT.get(Path(filename).suffix.lower())
    if kind:
        return kind
    if mimetype.startswith("audio/"):
        return "audio"
    if mimetype.startswith("video/"):
        return "video"
    return None


def _pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(f"[Page {i}]\n{text}")
    return "\n\n".join(pages)


def _pptx(path: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(path))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        parts = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            elif getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        parts.append(" | ".join(cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                parts.append(f"(Speaker notes) {notes}")
        if parts:
            slides.append(f"[Slide {i}]\n" + "\n".join(parts))
    return "\n\n".join(slides)


def _docx(path: Path) -> str:
    from docx import Document
    doc = Document(str(path))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)


def extract_text(path: Path, kind: str) -> str:
    try:
        if kind == "pdf":
            return _pdf(path)
        if kind == "slides":
            return _pptx(path)
        if kind == "document":
            return _docx(path)
        if kind == "text":
            return path.read_text(encoding="utf-8", errors="ignore")
    except ImportError as exc:
        raise ExtractError(f"A reader for {kind} files is missing ({exc.name}). Start the app with Run & Go to install it.") from exc
    except Exception as exc:
        raise ExtractError(f"Could not read {path.name}: {exc}") from exc
    raise ExtractError(f"Unsupported file type: {kind}")
