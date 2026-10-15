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


class _DataFolderCase(unittest.TestCase):
    """A data folder (database, preferences) and an export folder in a temp directory, with
    config pointed at them."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.data, self.exports = root / "data", root / "Downloads"
        self.data.mkdir()
        self.exports.mkdir()
        self.db, self.prefs = self.data / "pokemon_champions.db", self.data / "preferences.json"
        for name, value in (("DEFAULT_DATABASE_FILENAME", str(self.db)), ("DEFAULT_PREFERENCES_FILENAME", str(self.prefs)),
                            ("EXPORT_DIR", self.exports)):
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        storage.LAST_RESTORE = None

    def tearDown(self):
        while _OPEN:
            _OPEN.pop().close()
        storage.LAST_RESTORE = None
        self._tmp.cleanup()

    def _database(self, rows=3, schema=None):
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE IF NOT EXISTS t (n INTEGER)")
        con.execute("DELETE FROM t")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
        if schema is not None:
            con.execute(f"PRAGMA user_version = {int(schema)}")
        con.commit()
        con.close()

    def _rows(self):
        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
        finally:
            con.close()


class TestBackupAndRestore(_DataFolderCase):
    def test_a_backup_round_trip_brings_back_the_data_and_the_preferences(self):
        from pokemon_champions_planning_tool.infrastructure.database.database import CURRENT_SCHEMA_VERSION

        self._database(rows=3, schema=CURRENT_SCHEMA_VERSION)
        self.prefs.write_text('{"formats.default": "champions"}', encoding="utf-8")
        backup = storage.create_backup()
        self.assertEqual(backup.parent, self.exports)
        self.assertTrue(backup.name.startswith(storage.BACKUP_PREFIX))
        info = storage.inspect_backup(backup)
        self.assertEqual((info.schema, info.has_preferences), (CURRENT_SCHEMA_VERSION, True))

        self._database(rows=7)                                # changed after the backup
        self.prefs.write_text('{"formats.default": "other"}', encoding="utf-8")
        storage.stage_restore(backup)
        self.assertIsNotNone(storage.pending_restore())
        self.assertEqual(self._rows(), 7, "staging changes nothing yet")

        restored = storage.apply_pending_restore()
        self.assertIsNotNone(restored)
        self.assertEqual(self._rows(), 3)
        self.assertEqual(self.prefs.read_text(encoding="utf-8"), '{"formats.default": "champions"}')
        self.assertIsNone(storage.pending_restore(), "the staged folder is gone")
        self.assertTrue(restored.saved_to and restored.saved_to.is_file(), "the replaced data was backed up first")
        self.assertIn("before-restore", restored.saved_to.name)
        self.assertEqual(storage.LAST_RESTORE, restored)

    def test_a_backup_includes_changes_still_in_the_wal(self):
        con = sqlite3.connect(self.db)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE t (n INTEGER)")
        con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(5)])
        con.commit()
        _OPEN.append(con)
        backup = storage.create_backup()
        with tempfile.TemporaryDirectory() as tmp:
            import zipfile
            with zipfile.ZipFile(backup) as zf:
                zf.extract(storage.DB_MEMBER, tmp)
            copy = sqlite3.connect(Path(tmp) / storage.DB_MEMBER)
            try:
                self.assertEqual(copy.execute("SELECT COUNT(*) FROM t").fetchone()[0], 5)
            finally:
                copy.close()

    def test_nothing_to_back_up_says_so(self):
        with self.assertRaisesRegex(storage.BackupError, "no data"):
            storage.create_backup()

    def test_bad_backups_are_refused_with_a_reason(self):
        import json
        import zipfile

        from pokemon_champions_planning_tool.infrastructure.database.database import CURRENT_SCHEMA_VERSION

        not_zip = self.exports / "x.zip"
        not_zip.write_text("hello")
        with self.assertRaisesRegex(storage.BackupError, "Can't read"):
            storage.inspect_backup(not_zip)

        def make(name, members):
            path = self.exports / name
            with zipfile.ZipFile(path, "w") as zf:
                for member, data in members.items():
                    zf.writestr(member, data)
            return path

        self._database(schema=CURRENT_SCHEMA_VERSION + 1)
        newer_db = self.db.read_bytes()
        manifest = json.dumps({"app": config.APP_NAME, "version": "9.9.9"})
        cases = {
            "no manifest": (make("a.zip", {storage.DB_MEMBER: newer_db}), "isn't a Champions MetaDesk backup"),
            "another app": (make("b.zip", {storage.DB_MEMBER: newer_db, storage.MANIFEST_MEMBER: json.dumps({"app": "Other"})}), "isn't a Champions MetaDesk backup"),
            "damaged database": (make("c.zip", {storage.DB_MEMBER: b"not sqlite" * 50, storage.MANIFEST_MEMBER: manifest}), "damaged"),
            "newer schema": (make("d.zip", {storage.DB_MEMBER: newer_db, storage.MANIFEST_MEMBER: manifest}), "newer version"),
        }
        for label, (path, message) in cases.items():
            with self.subTest(label):
                with self.assertRaisesRegex(storage.BackupError, message):
                    storage.stage_restore(path)
                self.assertIsNone(storage.pending_restore(), "nothing is staged")

    def test_a_failed_restore_keeps_the_current_data(self):
        self._database(rows=3)
        backup = storage.create_backup()
        storage.stage_restore(backup)
        self._database(rows=9)
        with patch.object(storage.os, "replace", side_effect=OSError("disk full")), \
                self.assertLogs("pokemon_champions_planning_tool.storage", "ERROR"):
            self.assertIsNone(storage.apply_pending_restore())
        self.assertEqual(self._rows(), 9)
        self.assertIsNone(storage.pending_restore())
        self.assertTrue(list(self.data.glob("restore-failed-*")) or not (self.data / "restore-pending").exists())

    def test_a_restore_can_be_cancelled(self):
        self._database()
        storage.stage_restore(storage.create_backup())
        storage.cancel_pending_restore()
        self.assertIsNone(storage.pending_restore())
        self.assertIsNone(storage.apply_pending_restore())

    def test_an_older_schema_is_backed_up_before_the_upgrade(self):
        from pokemon_champions_planning_tool.infrastructure.database.database import CURRENT_SCHEMA_VERSION

        self._database(schema=CURRENT_SCHEMA_VERSION)
        self.assertIsNone(storage.backup_before_upgrade(), "current schema: nothing to do")
        self._database(schema=CURRENT_SCHEMA_VERSION - 1)
        path = storage.backup_before_upgrade()
        self.assertIsNotNone(path)
        self.assertEqual(path.parent, self.data / "backups")
        self.assertIn(f"before-upgrade-v{CURRENT_SCHEMA_VERSION - 1}", path.name)

    def test_automatic_backups_keep_the_newest_five_and_the_list_is_newest_first(self):
        self._database()
        folder = self.data / "backups"
        made = []
        for i in range(7):
            path = storage.create_backup(folder, reason=f"auto{i}")
            os.utime(path, (1_000_000 + i, 1_000_000 + i))
            made.append(path)
        storage.prune_backups(folder)
        self.assertEqual(sorted(folder.glob("*.zip")), sorted(made[2:]))
        manual = storage.create_backup()
        listed = storage.list_backups()
        self.assertEqual(listed[0], manual.resolve(), "the newest first")
        self.assertEqual(len(listed), 6)
