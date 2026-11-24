"""
Student sign-up: one account in Remind Me Bro, plus the same email and password in UniSIS and UniLearn.

Remind Me Bro is a registered app for both systems: it creates the accounts with its own credentials
(UniSIS: OAuth client ID + secret; UniLearn: the provisioning key in data/unilearn) and connects them right
away, so a student who opened the public link never needs to reach UniSIS or UniLearn directly.
If a system is not running, the hub account is still created and the student can connect later.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.database.models import User
from app.services import unilearn_client, unisis_client

logger = logging.getLogger(__name__)


def create_student_accounts(db: Session, user: User, password: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        unisis_client.provision_student(db, user, password)
        unisis_client.sync_user(db, user)
        out["unisis"] = "connected"
    except unisis_client.UniSISError as exc:
        db.rollback()
        out["unisis"] = str(exc)
        logger.warning("UniSIS account for %s not created: %s", user.email, exc)
    first, _, last = user.full_name.strip().partition(" ")
    try:
        unilearn_client.provision_student(user.email, first or user.full_name, last, password)
        unilearn_client.connect(db, user, user.email, password)
        unilearn_client.sync_user(db, user, run_ai=False)
        out["unilearn"] = "connected"
    except unilearn_client.UniLearnError as exc:
        db.rollback()
        out["unilearn"] = str(exc)
        logger.warning("UniLearn account for %s not created: %s", user.email, exc)
    return out
