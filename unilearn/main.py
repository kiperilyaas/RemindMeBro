"""
UniLearn — demo learning platform with a Moodle-compatible web-service API.

Run from the project root:  uvicorn unilearn.main:app --port 8200
Site: http://127.0.0.1:8200   ·   Web services: /login/token.php and /webservice/rest/server.php
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from unilearn import staff, web, ws
from unilearn.config import settings
from unilearn.db import init_db, session_scope
from unilearn.seed import rotate_staff_passwords, seed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("unilearn")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if init_db():
        with session_scope() as db:
            seed(db)
    with session_scope() as db:
        rotate_staff_passwords(db)
    settings.provisioning_key()   # shared with the hub (same data folder) to create student accounts
    logger.info("UniLearn ready at %s", settings.public_url())
    yield


app = FastAPI(
    title="UniLearn web services",
    version=settings.RELEASE,
    description=(
        "Moodle-compatible REST web services (subset). Get a token with `login/token.php?service=moodle_mobile_app`, "
        "then call `webservice/rest/server.php?wstoken=…&wsfunction=…&moodlewsrestformat=json`.\n\n"
        f"Functions: {', '.join(ws.FUNCTIONS)}."
    ),
    lifespan=lifespan,
)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret(), session_cookie="unilearn_session", same_site="lax", max_age=8 * 3600)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(ws.router)
app.include_router(staff.router)
app.include_router(web.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    from fastapi.responses import Response
    return Response(status_code=204)
