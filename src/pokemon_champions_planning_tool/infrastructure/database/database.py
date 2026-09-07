"""Database engine and session helpers for SQLite storage."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import event
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

    engine = create_engine(
        _resolve_database_url(database_filename),
        # 30 s: a background sync commits while the UI reads; the default 5 s produced
        # "database is locked" under a long write.
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001 - DB-API objects
        # WAL lets readers and the one writer proceed together instead of taking turns;
        # NORMAL sync is safe under WAL and much cheaper per commit.
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
        except Exception:  # noqa: BLE001 - e.g. an in-memory database
            pass
        finally:
            cursor.close()

    return engine


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
        # team_members — Champions stat points (replaces the mainline EV/IV spread)
        "ALTER TABLE team_members ADD COLUMN points JSON NOT NULL DEFAULT '{}';",
        # moves — damage-formula fields; move_catalog_meta — schema version forcing a re-sync
        "ALTER TABLE moves ADD COLUMN mechanics JSON NOT NULL DEFAULT '{}';",
        "ALTER TABLE move_catalog_meta ADD COLUMN schema_version INTEGER NOT NULL DEFAULT 1;",
        # tournament_team_members — covering index for co-occurrence (partners) and per-team lookups
        "CREATE INDEX IF NOT EXISTS ix_tournament_team_members_team_species ON tournament_team_members (tournament_team_id, canonical_id);",
        # pokemon_records — explicit placeholder flag (records written without PokéAPI data)
        "ALTER TABLE pokemon_records ADD COLUMN is_placeholder BOOLEAN NOT NULL DEFAULT 0;",
        "UPDATE pokemon_records SET is_placeholder = 1 WHERE types = '[]' AND hp + attack + defense + special_attack + special_defense + speed = 0;",
        # tournament_teams — roster size (Box filter: size minus owned members)
        "ALTER TABLE tournament_teams ADD COLUMN member_count INTEGER NOT NULL DEFAULT 0;",
        # tournament_team_members — mega-stripped species id for box matching
        "ALTER TABLE tournament_team_members ADD COLUMN base_canonical_id VARCHAR NOT NULL DEFAULT '';",
        "CREATE INDEX IF NOT EXISTS ix_tournament_team_members_base_canonical_id ON tournament_team_members (base_canonical_id);",
        # tournament_team_members — moves per roster slot (usage ranking in the move picker)
        "ALTER TABLE tournament_team_members ADD COLUMN moves JSON NOT NULL DEFAULT '[]';",
        # tournaments — official tier (worlds/international/regional/special) or community
        "ALTER TABLE tournaments ADD COLUMN event_tier VARCHAR NOT NULL DEFAULT 'community';",
        "CREATE INDEX IF NOT EXISTS ix_tournaments_event_tier ON tournaments (event_tier);",
        # box_entries — drop unique index on pokemon_canonical_id if present
        "DROP INDEX IF EXISTS ix_box_entries_pokemon_canonical_id;",
        "CREATE INDEX IF NOT EXISTS ix_box_entries_pokemon_canonical_id ON box_entries (pokemon_canonical_id);",
        # mega_evolutions — abilities JSON column
        "ALTER TABLE mega_evolutions ADD COLUMN abilities JSON NOT NULL DEFAULT '[]';",
        # mega_evolutions — ability string column
        "ALTER TABLE mega_evolutions ADD COLUMN ability VARCHAR NOT NULL DEFAULT '';",
        # tournament_team_members — nature, item, ability columns
        "ALTER TABLE tournament_team_members ADD COLUMN nature VARCHAR;",
        "CREATE INDEX IF NOT EXISTS ix_tournament_team_members_nature ON tournament_team_members (nature);",
        "ALTER TABLE tournament_team_members ADD COLUMN item VARCHAR;",
        "CREATE INDEX IF NOT EXISTS ix_tournament_team_members_item ON tournament_team_members (item);",
        "ALTER TABLE tournament_team_members ADD COLUMN ability VARCHAR;",
        "CREATE INDEX IF NOT EXISTS ix_tournament_team_members_ability ON tournament_team_members (ability);",
    ]


    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore
        _backfill_event_tiers(conn)
        _backfill_member_moves(conn)
        _backfill_member_natures(conn)
        _backfill_member_base_ids(conn)
        _backfill_member_counts(conn)
        _backfill_default_form_labels(conn)
        _backfill_member_points(conn)

    _DB_INITIALIZED.add(database_filename)
    return engine


def _backfill_member_base_ids(conn) -> None:
    """Fill ``base_canonical_id`` for roster rows stored before the column existed.

    One UPDATE copies the id for every empty row (the common case), then the few rows
    whose id names a Mega or other battle-only form are corrected in Python. Idempotent.
    """
    from pokemon_champions_planning_tool.domain.pokemon_identity import base_canonical_id

    try:
        pending = conn.execute(text("SELECT COUNT(*) FROM tournament_team_members WHERE base_canonical_id = ''")).scalar()
    except Exception:
        return
    if not pending:
        return
    conn.execute(text("UPDATE tournament_team_members SET base_canonical_id = canonical_id WHERE base_canonical_id = ''"))
    rows = conn.execute(text(
        "SELECT DISTINCT canonical_id FROM tournament_team_members WHERE canonical_id LIKE '%-mega%' OR canonical_id LIKE '%-gmax' OR canonical_id LIKE '%-primal' OR canonical_id LIKE '%-eternamax'"
    )).fetchall()
    for (canonical_id,) in rows:
        base = base_canonical_id(canonical_id)
        if base != canonical_id:
            conn.execute(text("UPDATE tournament_team_members SET base_canonical_id = :base WHERE canonical_id = :cid"), {"base": base, "cid": canonical_id})
    conn.commit()


def _backfill_member_points(conn) -> None:
    """Convert legacy EV spreads on team members into Champions stat points.

    ``(EV + 4) // 8`` keeps every level-50 stat identical. Converted rows get their legacy
    columns cleared, so a spread the user later zeroes is never re-converted.
    """
    import json

    from ...domain.stat_calc import points_from_evs

    try:
        rows = conn.execute(text("SELECT team_member_id, evs FROM team_members WHERE points = '{}' AND evs != '{}'")).fetchall()
        for member_id, evs_json in rows:
            try:
                evs = json.loads(evs_json) if isinstance(evs_json, str) else dict(evs_json or {})
            except (TypeError, ValueError):
                evs = {}
            conn.execute(
                text("UPDATE team_members SET points = :points, evs = '{}', ivs = '{}', level = 50 WHERE team_member_id = :id"),
                {"points": json.dumps(points_from_evs(evs)), "id": member_id},
            )
        if rows:
            conn.commit()
    except Exception:
        return


def _backfill_default_form_labels(conn) -> None:
    """Label records fetched before default forms were named ("basculegion" → form "Male")."""
    from ...domain.pokemon_identity import DEFAULT_FORM_LABELS

    try:
        for canonical_id, label in DEFAULT_FORM_LABELS.items():
            conn.execute(
                text("UPDATE pokemon_records SET form_name = :label WHERE canonical_id = :cid AND lower(form_name) = 'base'"),
                {"label": label, "cid": canonical_id},
            )
        conn.commit()
    except Exception:
        return


def _backfill_member_counts(conn) -> None:
    """Fill tournament_teams.member_count for rows stored before the column existed."""
    try:
        pending = conn.execute(text("SELECT COUNT(*) FROM tournament_teams WHERE member_count = 0")).scalar()
    except Exception:
        return
    if not pending:
        return
    conn.execute(text(
        "UPDATE tournament_teams SET member_count = (SELECT COUNT(*) FROM tournament_team_members m WHERE m.tournament_team_id = tournament_teams.tournament_team_id) WHERE member_count = 0"
    ))
    conn.commit()


def _backfill_member_moves(conn) -> None:
    """Fill ``tournament_team_members.moves`` for rosters stored before the column existed.

    One pass over teams whose members all still have an empty list; each team's Showdown
    text is parsed once and the moves assigned by slot order. Idempotent.
    """
    import json as _json

    from pokemon_champions_planning_tool.services.showdown_service import parse_showdown_text

    try:
        rows = conn.execute(text(
            "SELECT t.tournament_team_id, t.showdown_text FROM tournament_teams t "
            "WHERE EXISTS (SELECT 1 FROM tournament_team_members m WHERE m.tournament_team_id = t.tournament_team_id) "
            "AND NOT EXISTS (SELECT 1 FROM tournament_team_members m WHERE m.tournament_team_id = t.tournament_team_id AND m.moves != '[]')"
        )).fetchall()
    except Exception:
        return
    if not rows:
        return
    for team_id, showdown_text in rows:
        try:
            slots = list(parse_showdown_text(showdown_text or "").slots)
        except Exception:  # noqa: BLE001 - one bad paste must not stop the pass
            continue
        members = conn.execute(text(
            "SELECT id, slot_position FROM tournament_team_members WHERE tournament_team_id = :tid ORDER BY slot_position"
        ), {"tid": team_id}).fetchall()
        for index, (member_id, _slot) in enumerate(members):
            moves = [m for m in (slots[index].moves if index < len(slots) else ()) if m]
            if moves:
                conn.execute(text("UPDATE tournament_team_members SET moves = :moves WHERE id = :id"), {"moves": _json.dumps(list(moves)), "id": member_id})
    conn.commit()


def _backfill_member_natures(conn) -> None:
    """Fill ``tournament_team_members.nature``, item, and ability for rosters stored before the columns existed."""
    from collections import defaultdict
    from pokemon_champions_planning_tool.services.showdown_service import parse_showdown_text

    try:
        already_done = conn.execute(text("SELECT 1 FROM tournament_team_members WHERE nature IS NOT NULL LIMIT 1")).scalar()
    except Exception:
        return
    if already_done:
        return

    try:
        team_texts = dict(conn.execute(text(
            "SELECT tournament_team_id, showdown_text FROM tournament_teams WHERE showdown_text IS NOT NULL AND showdown_text != ''"
        )).fetchall())
    except Exception:
        return
    if not team_texts:
        return

    try:
        members = conn.execute(text(
            "SELECT id, tournament_team_id, slot_position FROM tournament_team_members ORDER BY tournament_team_id, slot_position"
        )).fetchall()
    except Exception:
        return

    by_team: dict[Any, list[Any]] = defaultdict(list)
    for m_id, t_id, _slot_pos in members:
        by_team[t_id].append(m_id)

    updates: list[tuple[str | None, str | None, str | None, Any]] = []
    for t_id, m_ids in by_team.items():
        text_content = team_texts.get(t_id)
        if not text_content:
            continue
        try:
            slots = list(parse_showdown_text(text_content).slots)
        except Exception:
            continue
        for idx, m_id in enumerate(m_ids):
            if idx < len(slots):
                slot = slots[idx]
                nat = slot.nature.lower() if slot.nature else None
                itm = slot.item_name or None
                ab = slot.ability_name or None
                if nat or itm or ab:
                    updates.append((nat, itm, ab, m_id))

    if updates:
        raw_conn = getattr(conn, "connection", None)
        dbapi = getattr(raw_conn, "dbapi_connection", raw_conn)
        if dbapi is not None and hasattr(dbapi, "cursor"):
            cursor = dbapi.cursor()
            batch_size = 20000
            for i in range(0, len(updates), batch_size):
                batch = updates[i:i + batch_size]
                cursor.executemany("UPDATE tournament_team_members SET nature = ?, item = ?, ability = ? WHERE id = ?", batch)
                dbapi.commit()
        else:
            for nat, itm, ab, m_id in updates:
                conn.execute(
                    text("UPDATE tournament_team_members SET nature = :nat, item = :itm, ability = :ab WHERE id = :id"),
                    {"nat": nat, "itm": itm, "ab": ab, "id": m_id}
                )
            conn.commit()


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