"""
Live messages: every UNILEARN_POLL_SECONDS (default 30) the hub reads the announcement forums of every student
connected to UniLearn and the lecturers' emails and Teams posts in UniComms, so they reach the Inbox without
pressing Sync.
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
from app.services.sync_lock import try_exclusive

logger = logging.getLogger(__name__)
POLL_SECONDS = int(os.getenv("UNILEARN_POLL_SECONDS", "30"))
_started = False


def poll_once() -> int:
    with try_exclusive() as free:
        if not free:          # a Sync is running: it imports the same posts, skip this round
            return 0
        return _poll()


def _poll() -> int:
    from app.services import unicomms_client, unilearn_client
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
        try:
            new += unicomms_client.sync_messages(db)["new"]
        except Exception as exc:   # UniComms off: try again next round
            db.rollback()
            logger.debug("Live sync of UniComms skipped: %s", exc)
    finally:
        db.close()
    if new:
        logger.info("Live sync: %d new message(s) from UniLearn and UniComms", new)
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
