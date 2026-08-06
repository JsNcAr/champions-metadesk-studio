"""Database engine and session helpers for SQLite storage."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlmodel import SQLModel, Session, create_engine

from pokemon_champions_planning_tool.config import DEFAULT_DATABASE_FILENAME


def _resolve_database_url(database_filename: str) -> str:
    database_path = Path(database_filename)
    if not database_path.is_absolute():
        database_path = Path.cwd() / database_path
    return f"sqlite:///{database_path.resolve()}"


@lru_cache(maxsize=1)
def get_engine(database_filename: str = DEFAULT_DATABASE_FILENAME):
    """Return a cached SQLite engine."""

    return create_engine(
        _resolve_database_url(database_filename),
        connect_args={"check_same_thread": False},
    )


from sqlalchemy import text

# Guard: only run DDL once per process lifetime
_DB_INITIALIZED: set[str] = set()


def initialize_database(database_filename: str = DEFAULT_DATABASE_FILENAME):
    """Create all SQLModel tables if they do not already exist. Safe to call multiple times."""
    global _DB_INITIALIZED
    if database_filename in _DB_INITIALIZED:
        return get_engine(database_filename)

    from . import models  # noqa: F401 - registers SQLModel tables

    engine = get_engine(database_filename)
    SQLModel.metadata.create_all(engine)

    # Lightweight schema migration for selected_form column
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE team_members ADD COLUMN selected_form VARCHAR DEFAULT 'base';"))
            conn.commit()
        except Exception:
            pass  # Column already exists

    _DB_INITIALIZED.add(database_filename)
    return engine


@contextmanager
def get_session(database_filename: str = DEFAULT_DATABASE_FILENAME) -> Iterator[Session]:
    """Yield a session bound to the shared SQLite engine (DDL already initialized at startup)."""
    engine = get_engine(database_filename)
    with Session(engine) as session:
        yield session