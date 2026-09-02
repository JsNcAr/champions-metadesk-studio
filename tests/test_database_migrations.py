"""The additive migration list must upgrade an older database and be idempotent."""

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sqlmodel import SQLModel, create_engine

from pokemon_champions_planning_tool.infrastructure.database import database


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db_path = Path(self.dir) / "old.db"
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401

        engine = create_engine(f"sqlite:///{self.db_path}")
        SQLModel.metadata.create_all(engine)
        engine.dispose()
        # Simulate a database created before the column existed.
        conn = sqlite3.connect(self.db_path)
        conn.execute("ALTER TABLE team_members DROP COLUMN tera_type")
        conn.commit()
        conn.close()
        self.assertNotIn("tera_type", _columns(self.db_path, "team_members"))
        database.get_engine.cache_clear()
        database._DB_INITIALIZED.discard(str(self.db_path))

    def tearDown(self):
        database.get_engine.cache_clear()
        database._DB_INITIALIZED.discard(str(self.db_path))
        shutil.rmtree(self.dir)

    def test_initialize_adds_missing_column_and_is_idempotent(self):
        database.initialize_database(str(self.db_path))
        self.assertIn("tera_type", _columns(self.db_path, "team_members"))
        # Second run (fresh process simulated by clearing the guard) must not raise.
        database._DB_INITIALIZED.discard(str(self.db_path))
        database.get_engine.cache_clear()
        database.initialize_database(str(self.db_path))
        self.assertIn("tera_type", _columns(self.db_path, "team_members"))

    def test_event_tier_column_is_added_and_backfilled(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP INDEX IF EXISTS ix_tournaments_event_tier")
        conn.execute("ALTER TABLE tournaments DROP COLUMN event_tier")
        conn.execute(
            "INSERT INTO tournaments (tournament_id, name, event_date, format_regulation, game_platform, organizer, location, total_players, created_at, updated_at, standings_synced)"
            " VALUES ('vr', '2025 World Championships', '2025-08-14', 'Regulation H', 'Scarlet & Violet', 'Play! Pokémon Premier Events', 'Anaheim', 400, '2025-08-14', '2025-08-14', 1),"
            " ('lim', 'Broome Regional', '2026-01-01', 'Regulation M-A', 'Pokémon Champions', 'Limitless Community', 'Online', 20, '2026-01-01', '2026-01-01', 1)"
        )
        conn.commit()
        conn.close()
        database.initialize_database(str(self.db_path))
        self.assertIn("event_tier", _columns(self.db_path, "tournaments"))
        conn = sqlite3.connect(self.db_path)
        tiers = dict(conn.execute("SELECT tournament_id, event_tier FROM tournaments").fetchall())
        conn.close()
        self.assertEqual(tiers, {"vr": "worlds", "lim": "community"})



    def test_base_canonical_id_is_added_and_backfilled(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP INDEX IF EXISTS ix_tournament_team_members_base_canonical_id")
        conn.execute("ALTER TABLE tournament_team_members DROP COLUMN base_canonical_id")
        conn.execute(
            "INSERT INTO tournaments (tournament_id, name, event_date, format_regulation, game_platform, organizer, location, total_players, created_at, updated_at, standings_synced, event_tier)"
            " VALUES ('t', 'T', '2026-01-01', 'Regulation M-B', 'Pokémon Champions', 'Limitless Community', 'Online', 8, '2026-01-01', '2026-01-01', 1, 'community')"
        )
        conn.execute(
            "INSERT INTO tournament_teams (tournament_team_id, tournament_id, player_name, placement, standing_label, showdown_text, source_dataset, sync_source, division, created_at)"
            " VALUES ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 't', 'p', 1, 'Place #1', 'x', 'limitless_api', 'limitless', 'masters', '2026-01-01')"
        )
        for i, cid in enumerate(("charizard-mega-y", "rotom-wash", "incineroar")):
            conn.execute(
                "INSERT INTO tournament_team_members (id, tournament_team_id, slot_position, canonical_id, species_name, moves)"
                f" VALUES ('{i:032x}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', {i + 1}, '{cid}', '{cid}', '[]')"
            )
        conn.commit()
        conn.close()
        database.initialize_database(str(self.db_path))
        self.assertIn("base_canonical_id", _columns(self.db_path, "tournament_team_members"))
        conn = sqlite3.connect(self.db_path)
        rows = dict(conn.execute("SELECT canonical_id, base_canonical_id FROM tournament_team_members").fetchall())
        conn.close()
        self.assertEqual(rows, {"charizard-mega-y": "charizard", "rotom-wash": "rotom-wash", "incineroar": "incineroar"})
        database._DB_INITIALIZED.discard(str(self.db_path))
        database.get_engine.cache_clear()
        database.initialize_database(str(self.db_path))


if __name__ == "__main__":
    unittest.main()
