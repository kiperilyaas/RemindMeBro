"""
UniComms — the university's demo mail (like Outlook) and chat (like Teams).

Lecturers send emails and Teams channel posts from /staff (only on the computer that runs the demo);
Remind Me Bro reads them with GET /api/v1/messages and puts them in the students' Inbox.

Run from the project root:  uvicorn unicomms.main:app --port 8300
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from starlette.middleware.sessions import SessionMiddleware

from unicomms import staff
from unicomms.config import settings
from unicomms.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("unicomms")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings.hub_key()   # shared with the hub (same data folder)
    logger.info("UniComms ready")
    yield


app = FastAPI(title="UniComms", version=settings.RELEASE, lifespan=lifespan,
              description="Demo mail and chat of the university. The hub reads `GET /api/v1/messages` with the `X-API-Key` header.")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret(), session_cookie="unicomms_session", same_site="lax", max_age=8 * 3600)
app.include_router(staff.router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)
