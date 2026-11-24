"""UniLearn configuration (environment variables override every default)."""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ACADEMIC_HUB_DATA_DIR", PROJECT_DIR / "data"))
UNILEARN_DIR = DATA_DIR / "unilearn"
UNILEARN_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    APP_NAME = "UniLearn"
    RELEASE = "4.4 (Moodle-compatible demo API)"
    SITE_NAME = os.getenv("UNILEARN_SITE_NAME", "UniLearn · Demo University of Economics and Finance")
    DATABASE_URL = os.getenv("UNILEARN_DATABASE_URL", f"sqlite:///{(UNILEARN_DIR / 'unilearn.db').as_posix()}")
    # Same demo clock as the hub and UniSIS
    REFERENCE_DATE = os.getenv("UNILEARN_REFERENCE_DATE", os.getenv("DEMO_REFERENCE_DATE", "now"))
    DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")
    MOBILE_SERVICE = "moodle_mobile_app"   # service name used by Moodle's mobile app and by Remind Me Bro

    def now(self) -> datetime:
        value = self.REFERENCE_DATE
        if value and value.lower() != "now":
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now()

    def public_url(self) -> str:
        return os.getenv("UNILEARN_PUBLIC_URL", "http://127.0.0.1:8200").rstrip("/")

    def provisioning_key(self) -> str:
        """Key the hub uses to create student accounts (POST /admin/tool/provision/student). Stays in data/unilearn."""
        env = os.getenv("UNILEARN_PROVISIONING_KEY")
        if env:
            return env
        path = UNILEARN_DIR / "provisioning.key"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32))
            try:
                path.chmod(0o600)
            except OSError:
                pass
        return path.read_text().strip()

    def session_secret(self) -> str:
        path = UNILEARN_DIR / ".session_secret"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
        return path.read_text().strip()


settings = Settings()
