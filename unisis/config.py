"""UniSIS configuration (environment variables override every default)."""
from __future__ import annotations

import os
import secrets
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ACADEMIC_HUB_DATA_DIR", PROJECT_DIR / "data"))
UNISIS_DIR = DATA_DIR / "unisis"
UNISIS_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    APP_NAME = "UniSIS"
    APP_VERSION = "1.0.0-demo"
    UNIVERSITY_NAME = os.getenv("UNISIS_UNIVERSITY", "Demo University · School of Economics and Finance")

    DATABASE_URL = os.getenv("UNISIS_DATABASE_URL", f"sqlite:///{(UNISIS_DIR / 'unisis.db').as_posix()}")
    # Where client credentials are exported (the hub reads them from here)
    CREDENTIALS_DIR = Path(os.getenv("UNISIS_CREDENTIALS_DIR", UNISIS_DIR / "clients"))

    # Same demo clock as the hub: windows and timetables are computed against this date
    REFERENCE_DATE = os.getenv("UNISIS_REFERENCE_DATE", os.getenv("DEMO_REFERENCE_DATE", "now"))

    ACCESS_TOKEN_TTL = int(os.getenv("UNISIS_ACCESS_TOKEN_TTL", "3600"))          # 1 hour
    REFRESH_TOKEN_TTL = int(os.getenv("UNISIS_REFRESH_TOKEN_TTL", str(30 * 86400)))  # 30 days
    AUTH_CODE_TTL = 300                                                              # 5 minutes

    DEMO_PASSWORD = os.getenv("DEMO_PASSWORD", "demo1234")
    HUB_CLIENT_ID = "remind-me-bro"
    HUB_CALLBACK_PATH = "/api/connections/unisis/callback"

    def now(self) -> datetime:
        """Business clock (registration windows, timetable)."""
        value = self.REFERENCE_DATE
        if value and value.lower() != "now":
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now()

    def session_secret(self) -> str:
        path = UNISIS_DIR / ".session_secret"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(48))
            try:
                path.chmod(0o600)
            except OSError:
                pass
        return path.read_text().strip()


settings = Settings()
