"""
Lecturer accounts get their own random password instead of the shared demo password.

At every start, a lecturer still using the demo password gets a new one. New passwords are written to
data/STAFF-PASSWORDS-hub.txt (this file never leaves the computer: the zip for collaborators skips data/).
"""
from __future__ import annotations

import logging
import secrets
from pathlib import Path
from typing import Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DATA_DIR, settings

logger = logging.getLogger(__name__)
STAFF_FILE = DATA_DIR / "STAFF-PASSWORDS-hub.txt"


def new_password() -> str:
    return secrets.token_urlsafe(9)   # 12 characters, letters, digits, - and _


def write_password_file(path: Path, title: str, rotated: List[Tuple[str, str]]) -> None:
    """Merges the new passwords into the file (one 'account  password' line each)."""
    rows: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "  " in line.strip():
                name, pw = line.split(None, 1)
                rows[name] = pw.strip()
    rows.update(dict(rotated))
    body = "\n".join(f"{name:<34}  {pw}" for name, pw in sorted(rows.items()))
    path.write_text(f"# {title}\n# Only on this computer. Do not share this file.\n{body}\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def rotate_lecturer_passwords(db: Session) -> List[str]:
    from app.api.auth import hash_password, verify_password   # local import: auth imports this module's siblings
    from app.database.models import User, UserRole
    rotated: List[Tuple[str, str]] = []
    for u in db.scalars(select(User).where(User.role == UserRole.PROFESSOR)):
        if verify_password(settings.DEMO_PASSWORD, u.hashed_password):
            pw = new_password()
            u.hashed_password = hash_password(pw)
            rotated.append((u.email, pw))
    if rotated:
        db.commit()
        write_password_file(STAFF_FILE, "Remind Me Bro · lecturer accounts (sign in only on this computer)", rotated)
        logger.info("New passwords for %s lecturer account(s): see %s", len(rotated), STAFF_FILE)
    return [e for e, _ in rotated]
