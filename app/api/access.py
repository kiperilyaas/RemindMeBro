"""
Who is asking: this computer or the public link?

The demo can be opened by anyone through a public link (ngrok, run-share-*). The lecturer area must stay on
the computer that runs the demo. A request counts as local only when it reaches the server directly on
127.0.0.1/localhost and carries no proxy header: ngrok (and any reverse proxy) always adds X-Forwarded-For
and sends the public host name.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

LOCAL_NAMES = {"127.0.0.1", "::1", "localhost"}
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "forwarded", "x-real-ip", "ngrok-trace-id")

STAFF_ONLY_LOCAL = HTTPException(
    status_code=403,
    detail="The lecturer area is only available on the computer that runs the demo. Sign in there.",
)


def is_local_request(request: Request) -> bool:
    if any(h in request.headers for h in PROXY_HEADERS):
        return False
    client = request.client.host if request.client else ""
    host = (request.headers.get("host") or "").strip().lower()
    host = host[1:host.index("]")] if host.startswith("[") and "]" in host else host.rsplit(":", 1)[0]
    return client in LOCAL_NAMES and host in LOCAL_NAMES
