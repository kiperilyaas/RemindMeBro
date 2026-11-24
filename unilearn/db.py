"""SQLAlchemy engine and sessions for UniLearn (its own database)."""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from unilearn.config import UNILEARN_DIR, settings

logger = logging.getLogger("unilearn")

DATA_VERSION = "unilearn-empty-1"
DATA_VERSION_FILE = UNILEARN_DIR / ".data_version"

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> bool:
    """Create tables. Returns True when the database is new (and must be seeded)."""
    from unilearn import models  # noqa: F401

    stored = DATA_VERSION_FILE.read_text().strip() if DATA_VERSION_FILE.exists() else None
    has_tables = bool(inspect(engine).get_table_names())
    if has_tables and stored != DATA_VERSION:
        logger.warning("UniLearn demo data is outdated: rebuilding the database")
        Base.metadata.drop_all(bind=engine)
        has_tables = False
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    DATA_VERSION_FILE.write_text(DATA_VERSION)
    return not has_tables


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def _add_missing_columns() -> None:
    """Small migration: a column added to a model is added to the existing table, so saved data is kept."""
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
