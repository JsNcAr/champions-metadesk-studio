"""The data folder: where a packaged build keeps its files, and copying an older packaged
build's data into it."""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_champions_planning_tool import config, storage
from pokemon_champions_planning_tool.config import APP_NAME, user_data_dir


class TestUserDataDir(unittest.TestCase):
    HOME = Path("/home/ash")

    def test_macos_uses_application_support(self):
        self.assertEqual(user_data_dir("darwin", {}, self.HOME), self.HOME / "Library" / "Application Support" / APP_NAME)

    def test_windows_uses_local_app_data(self):
        self.assertEqual(user_data_dir("win32", {"LOCALAPPDATA": "C:/Users/ash/AppData/Local"}, self.HOME),
                         Path("C:/Users/ash/AppData/Local") / APP_NAME)
        self.assertEqual(user_data_dir("win32", {}, self.HOME), self.HOME / "AppData" / "Local" / APP_NAME)

    def test_linux_follows_xdg_data_home(self):
        self.assertEqual(user_data_dir("linux", {"XDG_DATA_HOME": "/data"}, self.HOME), Path("/data/champions-metadesk-studio"))
        self.assertEqual(user_data_dir("linux", {}, self.HOME), self.HOME / ".local" / "share" / "champions-metadesk-studio")


class TestPackagedPaths(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config)   # back to the paths of this (unpackaged) run

    def test_a_packaged_build_keeps_its_files_in_the_per_user_folder(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, "frozen", True, create=True), \
                patch.dict(os.environ, {"XDG_DATA_HOME": tmp, "LOCALAPPDATA": tmp, "HOME": tmp}):
            os.environ.pop("PCPT_DATABASE", None)
            os.environ.pop("PCPT_PREFERENCES", None)
            importlib.reload(config)
            folder = user_data_dir()
            self.assertTrue(config.FROZEN)
            self.assertEqual(Path(config.DEFAULT_DATABASE_FILENAME), folder / "pokemon_champions.db")
            self.assertEqual(Path(config.DEFAULT_PREFERENCES_FILENAME), folder / "preferences.json")
            self.assertEqual(Path(config.LOG_DIR), folder / "logs")
            self.assertFalse(folder.exists(), "importing config creates nothing")

    def test_pcpt_database_still_wins_in_a_packaged_build(self):
        with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"PCPT_DATABASE": "/tmp/pcpt/x.db"}):
            importlib.reload(config)
            self.assertEqual(config.DEFAULT_DATABASE_FILENAME, "/tmp/pcpt/x.db")

    def test_a_source_run_keeps_the_working_directory(self):
        os.environ.pop("PCPT_DATABASE", None)
        importlib.reload(config)
        self.assertFalse(config.FROZEN)
        self.assertEqual(config.DATA_DIR, Path())
        self.assertEqual(config.DEFAULT_CSV_FILENAME, "pokemon_team_stats.csv")


def _wal_database(path: Path, rows: int = 3) -> None:
    """A WAL database whose last row is still only in the -wal file (no checkpoint)."""
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.execute("CREATE TABLE t (n INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    con.commit()
    _OPEN.append(con)   # left open: closing the last connection would checkpoint the -wal


_OPEN: list[sqlite3.Connection] = []   # closed in tearDown


class TestMigrateLegacyData(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.old, self.new = root / "old", root / "new"
        self.old.mkdir()
        self.new.mkdir()
        self.target = self.new / "pokemon_champions.db"
        storage.LAST_MIGRATION = None

    def tearDown(self):
        while _OPEN:
            _OPEN.pop().close()
        storage.LAST_MIGRATION = None
        self._tmp.cleanup()

    def _migrate(self, **kw):
        kw.setdefault("frozen", True)
        kw.setdefault("env", {})
        return storage.migrate_legacy_data(target=self.target, candidates=[self.old], **kw)

    def test_copies_the_database_with_its_wal_changes_and_the_preferences(self):
        _wal_database(self.old / "pokemon_champions.db")
        self.assertTrue((self.old / "pokemon_champions.db-wal").stat().st_size > 0, "the rows are still in the -wal")
        (self.old / "preferences.json").write_text('{"nav": "calc"}', encoding="utf-8")
        with self.assertLogs("pokemon_champions_planning_tool.storage", "INFO") as logs:
            self.assertEqual(self._migrate(), self.old.resolve())
        con = sqlite3.connect(self.target)
        try:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM t").fetchone()[0], 3)
        finally:
            con.close()
        self.assertEqual((self.new / "preferences.json").read_text(encoding="utf-8"), '{"nav": "calc"}')
        self.assertTrue((self.old / "pokemon_champions.db").exists(), "the old files stay")
        self.assertEqual(storage.LAST_MIGRATION, self.old.resolve())
        self.assertIn("Copied your data", logs.output[0])
        self.assertFalse((self.new / "pokemon_champions.db.copying").exists())

    def test_does_nothing_when_the_folder_already_has_a_database(self):
        _wal_database(self.old / "pokemon_champions.db")
        self.target.write_bytes(b"")
        self.assertIsNone(self._migrate())
        self.assertEqual(self.target.read_bytes(), b"")

    def test_does_nothing_outside_a_packaged_build_or_with_pcpt_database(self):
        _wal_database(self.old / "pokemon_champions.db")
        self.assertIsNone(self._migrate(frozen=False))
        self.assertIsNone(self._migrate(env={"PCPT_DATABASE": "/elsewhere.db"}))
        self.assertFalse(self.target.exists())

    def test_does_nothing_without_old_data(self):
        self.assertIsNone(self._migrate())
        self.assertFalse(self.target.exists())

    def test_a_file_that_is_not_a_database_is_logged_and_skipped(self):
        (self.old / "pokemon_champions.db").write_bytes(b"not a database at all, just text" * 10)
        with self.assertLogs("pokemon_champions_planning_tool.storage", "WARNING"):
            self.assertIsNone(self._migrate())
        self.assertFalse(self.target.exists())
        self.assertFalse((self.new / "pokemon_champions.db.copying").exists())
        self.assertIsNone(storage.LAST_MIGRATION)


class TestPrepareDataDir(unittest.TestCase):
    def test_creates_nested_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "a" / "b" / "pokemon_champions.db"
            self.assertEqual(storage.prepare_data_dir(db), db.parent.resolve())
            self.assertTrue(db.parent.is_dir())

    def test_an_impossible_folder_names_itself_in_the_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "file"
            blocker.write_text("x")
            with self.assertRaisesRegex(OSError, "Can't create the data folder"):
                storage.prepare_data_dir(blocker / "sub" / "pokemon_champions.db")


if __name__ == "__main__":
    unittest.main()
