"""
Speech-to-text for lesson recordings with faster-whisper, on this computer (nothing is sent anywhere).

faster-whisper decodes audio and video with PyAV, which ships its own FFmpeg libraries.
The model (WHISPER_MODEL, default "base", about 150 MB) is downloaded once into data/whisper.
Run & Go downloads it at start-up:  python -m app.services.notes.transcribe --download
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Optional, Tuple

from app.config import settings

logger = logging.getLogger(__name__)
_model = None
_lock = threading.Lock()


class TranscribeError(Exception):
    pass


def is_installed() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def get_model():
    global _model
    with _lock:
        if _model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise TranscribeError("faster-whisper is not installed. Start the app with Run & Go to install it.") from exc
            Path(settings.WHISPER_DIR).mkdir(parents=True, exist_ok=True)
            logger.info("Loading Whisper model '%s'", settings.WHISPER_MODEL)
            _model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8", download_root=settings.WHISPER_DIR)
        return _model


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


class TranscribeStopped(RuntimeError):
    """The student pressed Stop during a transcription."""


def transcribe(path: Path, should_stop=None) -> Tuple[str, Optional[str]]:
    """Returns (text, language code). should_stop() True between two segments -> TranscribeStopped."""
    model = get_model()
    try:
        segments, info = model.transcribe(str(path), beam_size=1, vad_filter=True)
        # one paragraph per minute or so, each with its time: "[12:30]", so answers can say where it was said
        parts, cur, start = [], [], None
        for s in segments:
            if should_stop and should_stop():
                raise TranscribeStopped("Stopped.")
            if not s.text.strip():
                continue
            if start is None:
                start = s.start
            cur.append(s.text.strip())
            if s.end - start >= 60:
                parts.append(f"[{_clock(start)}]\n" + " ".join(cur))
                cur, start = [], None
        if cur:
            parts.append(f"[{_clock(start or 0)}]\n" + " ".join(cur))
        text = "\n\n".join(parts)
    except TranscribeStopped:
        raise
    except Exception as exc:
        raise TranscribeError(f"Could not transcribe {path.name}: {exc}") from exc
    return text, getattr(info, "language", None)


if __name__ == "__main__":
    if "--download" in sys.argv:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        try:
            get_model()
            print(f"Whisper model '{settings.WHISPER_MODEL}' ready in {settings.WHISPER_DIR}")
        except Exception as exc:  # never stop Run & Go for this
            print(f"Whisper model not downloaded yet ({exc}). Smart Notes will try again on the first recording.")
