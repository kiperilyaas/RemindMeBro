"""
Live messages: every UNILEARN_POLL_SECONDS (default 30) the hub reads the announcement forums of every student
connected to UniLearn, so a lecturer's "Post an announcement" reaches the Inbox without pressing Sync.
New posts also go through the AI (hidden deadlines). Set UNILEARN_POLL_SECONDS=0 to turn it off.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from sqlalchemy import select

from app.database.db import SessionLocal
from app.database.models import Connection, User

logger = logging.getLogger(__name__)
POLL_SECONDS = int(os.getenv("UNILEARN_POLL_SECONDS", "30"))
_started = False


def poll_once() -> int:
    from app.services import unilearn_client
    new = 0
    db = SessionLocal()
    try:
        ids = list(db.scalars(select(Connection.user_id).where(Connection.provider == unilearn_client.PROVIDER, Connection.status == "connected")))
        for uid in ids:
            user = db.get(User, uid)
            if user is None:
                continue
            try:
                new += unilearn_client.sync_posts(db, user)["new"]
            except Exception as exc:   # UniLearn off, token revoked, AI busy...: try again next round
                db.rollback()
                logger.debug("Live sync skipped for user %s: %s", uid, exc)
    finally:
        db.close()
    if new:
        logger.info("Live sync: %d new UniLearn announcement(s)", new)
    return new


def _loop() -> None:
    time.sleep(10)   # let the three services finish starting
    while True:
        try:
            poll_once()
        except Exception:
            logger.exception("Live sync failed")
        time.sleep(POLL_SECONDS)


def start() -> None:
    global _started
    if _started or POLL_SECONDS <= 0:
        return
    _started = True
    threading.Thread(target=_loop, name="unilearn-live-sync", daemon=True).start()
    logger.info("Live sync of UniLearn announcements every %ss", POLL_SECONDS)
