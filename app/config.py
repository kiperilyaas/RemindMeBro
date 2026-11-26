"""
Configurazione centralizzata dell'applicazione.

Tutti i parametri sono sovrascrivibili tramite variabili d'ambiente,
così la demo resta 100% locale ma facilmente adattabile.
"""
import os
import secrets
from datetime import datetime
from pathlib import Path

# Cartella radice del progetto (academic_hub_backend/)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("ACADEMIC_HUB_DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


class Settings:
    """Impostazioni dell'applicazione (lette una sola volta all'avvio)."""

    APP_NAME: str = "Academic Unified Hub & AI Assistant"
    APP_VERSION: str = "0.1.0-poc"

    # --- Database relazionale (SQLite) ---
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(DATA_DIR / 'academic_hub.db').as_posix()}"
    )

    # --- Vector DB (ChromaDB) ---
    # "persistent" salva su disco in data/chroma, "memory" tiene tutto in RAM
    CHROMA_MODE: str = os.getenv("CHROMA_MODE", "persistent")
    CHROMA_PATH: str = os.getenv("CHROMA_PATH", str(DATA_DIR / "chroma"))
    CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "academic_announcements")
    # "default" = all-MiniLM-L6-v2 (ONNX, scaricato una volta da Chroma, poi offline)
    # "ollama"  = embedding generati da Ollama (richiede `ollama pull nomic-embed-text`)
    CHROMA_EMBEDDING: str = os.getenv("CHROMA_EMBEDDING", "default")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # --- LLM locale (Ollama) ---
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    OLLAMA_TIMEOUT: float = float(os.getenv("OLLAMA_TIMEOUT", "120"))

    # --- Data di riferimento ---
    # Data di "oggi" usata dall'LLM per risolvere espressioni relative
    # ("domani", "venerdì prossimo"). Default "now": l'orologio del computer, sempre aggiornato.
    # Per fissare una data (prove, registrazioni) usa DEMO_REFERENCE_DATE=2026-11-24T09:00:00.
    DEMO_REFERENCE_DATE: str = os.getenv("DEMO_REFERENCE_DATE", "now")

    # --- Autenticazione (JWT) ---
    # Se non impostata, viene generata una chiave casuale e salvata in data/.jwt_secret
    # (così i token restano validi tra un riavvio e l'altro di uvicorn --reload).
    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 12)))

    # --- Demo ---
    # Crea all'avvio gli account demo (studente + un docente per ogni corso mock)
    DEMO_SEED_USERS: bool = os.getenv("DEMO_SEED_USERS", "true").lower() in {"1", "true", "yes"}
    DEMO_PASSWORD: str = os.getenv("DEMO_PASSWORD", "demo1234")

    # --- UniSIS (student information system) ---
    # UniLearn: the Moodle-compatible LMS (any real Moodle URL works too)
    UNILEARN_URL: str = os.getenv("UNILEARN_URL", "http://127.0.0.1:8200").rstrip("/")
    UNISIS_URL: str = os.getenv("UNISIS_URL", "http://127.0.0.1:8100").rstrip("/")
    UNISIS_CLIENT_ID: str = os.getenv("UNISIS_CLIENT_ID", "remind-me-bro")
    # Secret/API key: env vars, otherwise the credentials file exported by UniSIS
    UNISIS_CLIENT_SECRET: str = os.getenv("UNISIS_CLIENT_SECRET", "")
    UNISIS_API_KEY: str = os.getenv("UNISIS_API_KEY", "")
    UNISIS_CREDENTIALS_FILE: str = os.getenv("UNISIS_CREDENTIALS_FILE", str(DATA_DIR / "unisis" / "clients" / "remind-me-bro.json"))
    UNISIS_SCOPES: str = "profile timetable enrollments enrollments:write exams exams:write grades"

    # --- Premium plan (Ask Bro + Smart Notes) ---
    # Price shown in the app. Change it here (or with the environment variables) and restart the app.
    PREMIUM_PRICE: str = os.getenv("PREMIUM_PRICE", "79")
    PREMIUM_CURRENCY: str = os.getenv("PREMIUM_CURRENCY", "CZK")
    PREMIUM_PERIOD: str = os.getenv("PREMIUM_PERIOD", "month")

    # --- Smart Notes ---
    # Speech-to-text runs on this computer with faster-whisper (tiny | base | small | medium). "base" is quick on a laptop.
    WHISPER_MODEL: str = os.getenv("WHISPER_MODEL", "base")
    # Downloaded course files and the Whisper model stay in data/
    MATERIALS_DIR: str = os.getenv("MATERIALS_DIR", str(DATA_DIR / "materials"))
    WHISPER_DIR: str = os.getenv("WHISPER_DIR", str(DATA_DIR / "whisper"))
    # Context window asked of Ollama when it writes the notes (llama3.2 supports much more than the default 2048)
    NOTES_NUM_CTX: int = int(os.getenv("NOTES_NUM_CTX", "8192"))
    # Notes and "Ask the material" read long texts: on a slow computer the model can think for minutes before the
    # first word. The answer is streamed, and this is the longest wait (seconds) without any new word from Ollama.
    NOTES_TIMEOUT: float = float(os.getenv("NOTES_TIMEOUT", "1800"))

    # --- Frontend ---
    # Se il file esiste, viene servito su http://127.0.0.1:8000/ (stessa origine, niente CORS)
    CLASSIC_FRONTEND_PATH: str = os.getenv("CLASSIC_FRONTEND_PATH", str(BASE_DIR / "frontend" / "index.html"))
    # New React UI (built from web/ into a single HTML file); falls back to the classic page if missing
    FRONTEND_PATH: str = os.getenv("FRONTEND_PATH", str(BASE_DIR / "frontend" / "app" / "index.html"))
    # Origini ammesse per CORS (default: tutte, adatto a una demo locale)
    CORS_ORIGINS: list = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

    def jwt_secret(self) -> str:
        """Ritorna la chiave JWT (env var oppure chiave persistita in data/)."""
        if self.JWT_SECRET_KEY:
            return self.JWT_SECRET_KEY
        secret_file = DATA_DIR / ".jwt_secret"
        if not secret_file.exists():
            secret_file.write_text(secrets.token_urlsafe(48))
            try:
                secret_file.chmod(0o600)
            except OSError:
                pass
        self.JWT_SECRET_KEY = secret_file.read_text().strip()
        return self.JWT_SECRET_KEY

    def reference_now(self) -> datetime:
        """Ritorna il 'now' di riferimento per la demo."""
        if self.DEMO_REFERENCE_DATE and self.DEMO_REFERENCE_DATE.lower() != "now":
            try:
                return datetime.fromisoformat(self.DEMO_REFERENCE_DATE)
            except ValueError:
                pass
        return datetime.now()


settings = Settings()
