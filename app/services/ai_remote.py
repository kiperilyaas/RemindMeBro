"""
External AI through any OpenAI-compatible API (/chat/completions): Google Gemini, OpenRouter, OmniRoute, OpenAI...

Chosen in data/ai.env (see ai.env.example): AI_PROVIDER, AI_API_KEY, optionally AI_MODEL, AI_MODEL_FAST, AI_BASE_URL.
llm_extractor.py calls chat() and chat_stream(); when the external AI cannot answer it falls back to Ollama.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RemoteAIError(RuntimeError):
    """The external AI answered with an error. `retry_local` = worth trying Ollama instead (network, quota, server)."""

    def __init__(self, message: str, retry_local: bool = True, status: int = 0):
        super().__init__(message)
        self.retry_local = retry_local
        self.status = status


class RemoteStopped(RuntimeError):
    pass


def _headers() -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if settings.AI_API_KEY:
        h["Authorization"] = f"Bearer {settings.AI_API_KEY}"
    if settings.AI_PROVIDER == "openrouter":
        h["X-Title"] = "Remind Me Bro"
    return h


def _body(messages: List[Dict[str, str]], json_mode: bool, temperature: Optional[float], fast: bool,
          stream: bool, extras: bool) -> Dict[str, Any]:
    body: Dict[str, Any] = {"model": settings.AI_MODEL_FAST if fast else settings.AI_MODEL, "messages": messages, "stream": stream}
    if temperature is not None:
        body["temperature"] = temperature
    if extras:   # optional fields: some services refuse them, then the request is sent again without
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if settings.AI_REASONING_EFFORT:
            body["reasoning_effort"] = settings.AI_REASONING_EFFORT
    return body


def _error(status: int, text: str) -> RemoteAIError:
    try:
        data = json.loads(text)
        data = data[0] if isinstance(data, list) and data else data
        msg = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error")
    except (ValueError, AttributeError):
        msg = None
    msg = (msg or text or "").strip()[:300]
    who = settings.AI_LABEL
    if status in (401, 403):
        return RemoteAIError(f"{who} refused the API key ({status}). Check AI_API_KEY in data/ai.env. {msg}", retry_local=True, status=status)
    if status == 404:
        return RemoteAIError(f"{who} does not know the model '{settings.AI_MODEL}' (404). Check AI_MODEL in data/ai.env. {msg}", status=status)
    if status == 429:
        return RemoteAIError(f"{who}: too many requests or the free quota is used up (429). {msg}", status=status)
    return RemoteAIError(f"{who} answered with an error ({status}): {msg}", status=status)


def chat(messages: List[Dict[str, str]], json_mode: bool = False, temperature: Optional[float] = 0.0, fast: bool = False) -> str:
    """One answer, not streamed (deadlines in messages, Ask Bro)."""
    url = f"{settings.AI_BASE_URL}/chat/completions"
    for extras in (True, False):
        try:
            r = httpx.post(url, headers=_headers(), json=_body(messages, json_mode, temperature, fast, False, extras),
                           timeout=httpx.Timeout(settings.AI_TIMEOUT, connect=10.0))
        except httpx.TimeoutException as exc:
            raise RemoteAIError(f"{settings.AI_LABEL} gave no answer in {int(settings.AI_TIMEOUT)} s.") from exc
        except httpx.HTTPError as exc:
            raise RemoteAIError(f"{settings.AI_LABEL} is not reachable ({settings.AI_BASE_URL}): {exc}") from exc
        if r.status_code == 400 and extras:
            logger.info("%s refused an optional field, sending again without: %s", settings.AI_LABEL, r.text[:200])
            continue
        if r.status_code != 200:
            raise _error(r.status_code, r.text)
        data = r.json()
        data = data[0] if isinstance(data, list) and data else data
        try:
            return (data["choices"][0]["message"].get("content") or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise RemoteAIError(f"{settings.AI_LABEL} sent an answer without text.") from exc
    raise RemoteAIError(f"{settings.AI_LABEL} refused the request (400).")


def chat_stream(messages: List[Dict[str, str]], json_mode: bool = False, temperature: Optional[float] = None,
                should_stop: Optional[Callable[[], bool]] = None) -> str:
    """
    A long job (Smart Notes, Ask the material), streamed. The wait limit (NOTES_TIMEOUT) counts from the last
    piece received. should_stop is checked twice a second: when it returns True the socket is shut down and
    RemoteStopped is raised (same mechanism as for Ollama).
    """
    url = f"{settings.AI_BASE_URL}/chat/completions"
    socks: List[Any] = []
    done, stopped = threading.Event(), threading.Event()

    def trace(event: str, info: Dict[str, Any]) -> None:
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
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return

    if should_stop:
        threading.Thread(target=watch, name="ai-stop-watch", daemon=True).start()
    try:
        for extras in (True, False):
            parts: List[str] = []
            try:
                with httpx.Client(timeout=httpx.Timeout(settings.NOTES_TIMEOUT, connect=10.0)) as client:
                    with client.stream("POST", url, headers=_headers(), json=_body(messages, json_mode, temperature, False, True, extras),
                                       extensions={"trace": trace}) as r:
                        if r.status_code != 200:
                            text = r.read().decode("utf-8", "replace")
                            if r.status_code == 400 and extras:
                                continue
                            raise _error(r.status_code, text)
                        for line in r.iter_lines():
                            if stopped.is_set():
                                raise RemoteStopped("Stopped.")
                            line = line.strip()
                            if not line.startswith("data:"):
                                continue
                            payload = line[5:].strip()
                            if payload == "[DONE]":
                                break
                            chunk = json.loads(payload)
                            if chunk.get("error"):
                                raise _error(500, json.dumps(chunk))
                            for ch in chunk.get("choices") or []:
                                parts.append((ch.get("delta") or {}).get("content") or "")
                return "".join(parts)
            except (RemoteStopped, RemoteAIError):
                raise
            except Exception as exc:
                if stopped.is_set():
                    raise RemoteStopped("Stopped.") from exc
                if isinstance(exc, httpx.TimeoutException):
                    raise RemoteAIError(f"{settings.AI_LABEL} gave no answer for {round(settings.NOTES_TIMEOUT / 60)} minutes.") from exc
                raise RemoteAIError(f"{settings.AI_LABEL} is not reachable ({settings.AI_BASE_URL}): {exc}") from exc
        raise RemoteAIError(f"{settings.AI_LABEL} refused the request (400).")
    finally:
        done.set()
        if stopped.is_set():
            raise RemoteStopped("Stopped.")


_status_cache: Dict[str, Any] = {"at": 0.0, "value": None}


def status() -> Dict[str, Any]:
    """Health check (cached for a minute): is the service reachable, is the key accepted, does the model exist?"""
    if _status_cache["value"] is not None and time.time() - _status_cache["at"] < 60:
        return _status_cache["value"]
    out: Dict[str, Any] = {"provider": settings.AI_PROVIDER, "label": settings.AI_LABEL, "local": False,
                           "model": settings.AI_MODEL, "fast_model": settings.AI_MODEL_FAST}
    try:
        r = httpx.get(f"{settings.AI_BASE_URL}/models", headers=_headers(), timeout=8)
        if r.status_code == 200:
            data = r.json()
            ids = {str(m.get("id", "")).split("/")[-1] for m in (data.get("data") or [])} if isinstance(data, dict) else set()
            known = not ids or settings.AI_MODEL.split("/")[-1] in ids
            out.update(reachable=True, model_available=known)
            if not known:
                out["error"] = f"Model {settings.AI_MODEL} not found at {settings.AI_LABEL}"
        else:
            out.update(reachable=r.status_code not in (401, 403), model_available=False, error=str(_error(r.status_code, r.text)))
    except httpx.HTTPError as exc:
        out.update(reachable=False, model_available=False, error=f"{settings.AI_LABEL} is not reachable: {exc}")
    _status_cache.update(at=time.time(), value=out)
    return out


def main() -> int:
    """Check the AI in data/ai.env:  .runtime/venv/bin/python -m app.services.ai_remote"""
    if not settings.ai_remote:
        print(f"No external AI configured (AI_PROVIDER={settings.AI_PROVIDER}, key {'set' if settings.AI_API_KEY else 'missing'}): "
              f"the app uses the local AI (Ollama, {settings.OLLAMA_MODEL}). Edit data/ai.env to change it.")
        return 1
    print(f"AI: {settings.AI_LABEL} · {settings.AI_BASE_URL}")
    print(f"Models: {settings.AI_MODEL} (main), {settings.AI_MODEL_FAST} (fast)")
    st = status()
    print(f"Service: {'reachable' if st.get('reachable') else 'NOT reachable'} · model {'found' if st.get('model_available') else 'NOT found'}"
          + (f" · {st['error']}" if st.get("error") else ""))
    ok = True
    for fast, json_mode, q in ((False, False, "Answer with one short sentence: what is 2 + 2?"),
                               (True, True, 'Reply only with this JSON object: {"ok": true}')):
        t = time.time()
        try:
            answer = chat([{"role": "user", "content": q}], json_mode=json_mode, fast=fast)
            print(f"{'Fast' if fast else 'Main'} model answered in {time.time() - t:.1f} s: {answer[:120]!r}")
        except RemoteAIError as exc:
            ok = False
            print(f"{'Fast' if fast else 'Main'} model: ERROR {exc}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
