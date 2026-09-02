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

    # Lightweight schema migrations — each ALTER TABLE is wrapped in its own
    # try/except so a pre-existing column never aborts the others.
    migrations = [
        # team_members — original migration (form field)
        "ALTER TABLE team_members ADD COLUMN selected_form VARCHAR DEFAULT 'base';",
        # team_members — competitive spread fields (Phase 0.B)
        "ALTER TABLE team_members ADD COLUMN evs JSON NOT NULL DEFAULT '{}';",
        "ALTER TABLE team_members ADD COLUMN ivs JSON NOT NULL DEFAULT '{}';",
        "ALTER TABLE team_members ADD COLUMN nature VARCHAR;",
        "ALTER TABLE team_members ADD COLUMN level INTEGER NOT NULL DEFAULT 50;",
        # box_entries — ghost/planned entry support (Phase 0.A)
        "ALTER TABLE box_entries ADD COLUMN is_planned BOOLEAN NOT NULL DEFAULT 0;",
        # tournaments — game platform / system filter (Feature 7)
        "ALTER TABLE tournaments ADD COLUMN game_platform VARCHAR DEFAULT 'Scarlet & Violet';",
        # tournaments — source URL for official / community events
        "ALTER TABLE tournaments ADD COLUMN source_url VARCHAR;",
        # tournament_teams — source tag ("seed" | "limitless" | "victory_road")
        "ALTER TABLE tournament_teams ADD COLUMN sync_source VARCHAR DEFAULT 'seed';",
        # tournaments — standings backlog flag; unsynced rows are retried each run
        "ALTER TABLE tournaments ADD COLUMN standings_synced BOOLEAN NOT NULL DEFAULT 0;",
        "CREATE INDEX IF NOT EXISTS ix_tournaments_standings_synced ON tournaments (standings_synced);",
        # tournament_teams — age division ("masters" only, as of the division-aware sync)
        "ALTER TABLE tournament_teams ADD COLUMN division VARCHAR NOT NULL DEFAULT 'masters';",
        "CREATE INDEX IF NOT EXISTS ix_tournament_teams_division ON tournament_teams (division);",
        # team_members — Terastallization type per slot
        "ALTER TABLE team_members ADD COLUMN tera_type VARCHAR;",
        # tournaments — official tier (worlds/international/regional/special) or community
        "ALTER TABLE tournaments ADD COLUMN event_tier VARCHAR NOT NULL DEFAULT 'community';",
        "CREATE INDEX IF NOT EXISTS ix_tournaments_event_tier ON tournaments (event_tier);",
        # box_entries — drop unique index on pokemon_canonical_id if present
        "DROP INDEX IF EXISTS ix_box_entries_pokemon_canonical_id;",
        "CREATE INDEX IF NOT EXISTS ix_box_entries_pokemon_canonical_id ON box_entries (pokemon_canonical_id);",
    ]


    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore
        _backfill_event_tiers(conn)

    _DB_INITIALIZED.add(database_filename)
    return engine


def _backfill_event_tiers(conn) -> None:
    """Classify tournaments that predate the event_tier column.

    Rows are created with the 'community' default; official events (Victory Road, seed)
    get their tier from organizer + name. Idempotent: only rows whose stored tier differs
    from the classification are written.
    """
    from pokemon_champions_planning_tool.domain.event_tier import classify_event_tier

    try:
        rows = conn.execute(text("SELECT tournament_id, name, organizer, event_tier FROM tournaments")).fetchall()
    except Exception:
        return
    changes = [
        (tier, tournament_id)
        for tournament_id, name, organizer, stored in rows
        if (tier := classify_event_tier(name, organizer)) != stored
    ]
    if not changes:
        return
    for tier, tournament_id in changes:
        conn.execute(text("UPDATE tournaments SET event_tier = :tier WHERE tournament_id = :id"), {"tier": tier, "id": tournament_id})
    conn.commit()


@contextmanager
def get_session(database_filename: str = DEFAULT_DATABASE_FILENAME) -> Iterator[Session]:
    """Yield a session bound to the shared SQLite engine (DDL initialized on demand)."""
    engine = initialize_database(database_filename)
    with Session(engine) as session:
        yield session