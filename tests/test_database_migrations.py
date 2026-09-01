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


if __name__ == "__main__":
    unittest.main()
