"""
Engine e sessioni SQLAlchemy per SQLite.
"""
import logging
from contextlib import contextmanager
from typing import Generator, Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATA_DIR, settings

logger = logging.getLogger(__name__)

# Versione dei dati demo: se cambia (es. nuovi corsi mock), il DB locale viene rigenerato.
DATA_VERSION = "empty-start-1"
DATA_VERSION_FILE = DATA_DIR / ".data_version"

# check_same_thread=False: FastAPI può usare la stessa connessione da thread diversi.
# timeout=30: a writer waits up to 30 s for the lock (Python's default is 5 s) before "database is locked".
_SQLITE = settings.DATABASE_URL.startswith("sqlite")
engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if _SQLITE else {},
    echo=False,
)

if _SQLITE:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        """WAL: pages keep loading (reads) while a sync writes; busy_timeout: writers queue instead of failing."""
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
        except Exception:   # some network/virtual file systems refuse WAL: the timeout alone still helps
            pass
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Classe base dichiarativa per tutti i modelli ORM."""


def _schema_is_outdated() -> bool:
    """Kept for compatibility: new tables and columns are now added in place (see _add_missing_columns)."""
    return False


def _add_missing_columns() -> None:
    """A column added to a model is added to the existing table, so users, connections and data are kept."""
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                if default is not None:
                    ddl += " DEFAULT " + (f"'{default}'" if isinstance(default, str) else str(int(default) if isinstance(default, bool) else default))
                conn.execute(text(ddl))
                logger.info("Added column %s.%s", table.name, col.name)


def init_db() -> bool:
    """
    Crea tutte le tabelle (idempotente).

    "Migrazione" da PoC: se lo schema su disco è di una versione precedente
    (es. manca la tabella `users`), il DB viene ricreato. Tutti i dati di dominio
    sono mock e vengono rigenerati dalla sincronizzazione. Lo stesso accade quando
    cambia DATA_VERSION (es. passaggio ai corsi di Economics & Finance).

    Ritorna True se il database è stato ricreato (il chiamante azzera anche ChromaDB).
    """
    # Import necessario per registrare i modelli sul metadata di Base
    from app.database import models  # noqa: F401

    stored_version = DATA_VERSION_FILE.read_text().strip() if DATA_VERSION_FILE.exists() else None
    has_tables = bool(inspect(engine).get_table_names())
    reset = _schema_is_outdated() or (has_tables and stored_version != DATA_VERSION)
    if reset:
        logger.warning("Schema/dati demo obsoleti: ricreo il database (i dati mock verranno rigenerati).")
        Base.metadata.drop_all(bind=engine)
        with engine.begin() as conn:  # rimuove anche tabelle orfane di versioni precedenti
            for name in inspect(engine).get_table_names():
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}"'))
    Base.metadata.create_all(bind=engine)   # adds new tables (e.g. deadline_done) to an existing database
    _add_missing_columns()
    DATA_VERSION_FILE.write_text(DATA_VERSION)
    return reset


def get_db() -> Generator[Session, None, None]:
    """Dependency FastAPI: apre una sessione per richiesta e la chiude sempre."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager per uso fuori da FastAPI (script, servizi)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
