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


def initialize_database(database_filename: str = DEFAULT_DATABASE_FILENAME):
    """Create all SQLModel tables if they do not already exist."""

    from . import models  # noqa: F401 - registers SQLModel tables

    engine = get_engine(database_filename)
    SQLModel.metadata.create_all(engine)
    return engine


@contextmanager
def get_session(database_filename: str = DEFAULT_DATABASE_FILENAME) -> Iterator[Session]:
    """Yield a session bound to the shared SQLite engine."""

    engine = initialize_database(database_filename)
    with Session(engine) as session:
        yield session