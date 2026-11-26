"""
UniSIS — demo Student Information System.

Run from the project root:  uvicorn unisis.main:app --port 8100
Portal: http://127.0.0.1:8100   ·   API docs: http://127.0.0.1:8100/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from unisis import api, staff, web
from unisis.config import settings
from unisis.db import SessionLocal, init_db, session_scope
from unisis.models import AuditLog
from unisis.seed import ensure_current_terms, ensure_hub_client, move_demo_courses, rotate_staff_passwords, seed, seed_timetable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("unisis")

AUDITED_PREFIXES = ("/api/v1/", "/oauth/token", "/oauth/revoke")


@asynccontextmanager
async def lifespan(app: FastAPI):
    fresh = init_db()
    with session_scope() as db:
        if fresh:
            seed(db)
        ensure_current_terms(db)
        move_demo_courses(db)
        seed_timetable(db)   # demo courses without weekly classes get the ones of the demo
        ensure_hub_client(db)
        rotate_staff_passwords(db)
    logger.info("UniSIS ready · business clock: %s", settings.now().strftime("%a %d %b %Y %H:%M"))
    yield


app = FastAPI(
    title="UniSIS API",
    version=settings.APP_VERSION,
    description=(
        f"Student Information System of **{settings.UNIVERSITY_NAME}** (demo).\n\n"
        "* Student data: OAuth 2.0 Authorization Code + PKCE (`/oauth/authorize`, `/oauth/token`), Bearer token with scopes.\n"
        "* Catalogue: `X-API-Key` header.\n"
        "* Registered clients, keys and the API audit log: sign in as `registrar` → *Apps & keys*."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def audit(request: Request, call_next):
    """Writes every API / token call to the audit log (shown in Apps & keys)."""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(AUDITED_PREFIXES):
        client_name, username = getattr(request.state, "audit", (None, None))
        db = SessionLocal()
        try:
            db.add(AuditLog(client_name=client_name, username=username, method=request.method, path=path, status_code=response.status_code))
            db.commit()
        finally:
            db.close()
    return response


app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret(),
    session_cookie="unisis_session",
    same_site="lax",
    max_age=8 * 3600,
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(api.router)
app.include_router(staff.router)
app.include_router(web.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)
