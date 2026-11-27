"""UniComms configuration (environment variables override every default)."""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ACADEMIC_HUB_DATA_DIR", PROJECT_DIR / "data"))
UNICOMMS_DIR = DATA_DIR / "unicomms"
UNICOMMS_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    APP_NAME = "UniComms"
    RELEASE = "1.0 (demo mail and chat)"
    DATABASE_URL = os.getenv("UNICOMMS_DATABASE_URL", f"sqlite:///{(UNICOMMS_DIR / 'unicomms.db').as_posix()}")
    REFERENCE_DATE = os.getenv("UNICOMMS_REFERENCE_DATE", os.getenv("DEMO_REFERENCE_DATE", "now"))
    MAIL_DOMAIN = os.getenv("UNICOMMS_MAIL_DOMAIN", "uni.demo")

    def now(self) -> datetime:
        value = self.REFERENCE_DATE
        if value and value.lower() != "now":
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now()

    def hub_key(self) -> str:
        """Key the hub sends (X-API-Key) to read the messages. Stays in data/unicomms, shared with the hub."""
        env = os.getenv("UNICOMMS_HUB_KEY")
        if env:
            return env
        path = UNICOMMS_DIR / "hub.key"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32))
            try:
                path.chmod(0o600)
            except OSError:
                pass
        return path.read_text().strip()

    def session_secret(self) -> str:
        path = UNICOMMS_DIR / ".session_secret"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
        return path.read_text().strip()


settings = Settings()
