"""The data folder: create it, and bring a packaged build's older data into it.

Earlier packaged builds on Windows and Linux kept their files in whatever folder they were
started from. A packaged build now uses the per-user folder (``config.user_data_dir``); the first launch
copies the database and preferences found in the old place. The old files are left where
they are, so nothing is lost if the copy goes wrong. Standard library only.
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

# The folder the data was copied from on this launch (for a one-time notice), or None.
LAST_MIGRATION: Path | None = None


def prepare_data_dir(database: str | os.PathLike[str] | None = None) -> Path:
    """Create the folder that holds the database (and preferences, logs and sprites).

    Raises ``OSError`` with the folder in its message: without it SQLite fails later with
    a much less helpful "unable to open database file"."""
    folder = Path(database or config.DEFAULT_DATABASE_FILENAME).resolve().parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"Can't create the data folder {folder}: {exc}") from exc
    return folder


def legacy_folders() -> list[Path]:
    """Where an older packaged build kept its files: the folder it was started from, and
    the executable's folder."""
    out: list[Path] = []
    for folder in (Path.cwd(), Path(sys.executable).parent):
        folder = folder.resolve()
        if folder not in out:
            out.append(folder)
    return out


def migrate_legacy_data(
    *, target: str | os.PathLike[str] | None = None, candidates: Iterable[Path] | None = None,
    frozen: bool | None = None, env: dict[str, str] | None = None,
) -> Path | None:
    """Copy an older packaged build's database and preferences into the data folder.

    Only for a packaged build without ``PCPT_DATABASE``, and only while the data folder
    has no database yet. Returns the folder copied from, or None. Never raises: a failed
    copy is logged and the app starts with an empty database instead.
    """
    global LAST_MIGRATION
    frozen = config.FROZEN if frozen is None else frozen
    env = os.environ if env is None else env
    target_db = Path(target or config.DEFAULT_DATABASE_FILENAME).resolve()
    if not frozen or env.get("PCPT_DATABASE") or target_db.exists():
        return None
    source = next((folder / target_db.name for folder in (candidates if candidates is not None else legacy_folders())
                   if folder.resolve() != target_db.parent and (folder / target_db.name).is_file()), None)
    if source is None:
        return None
    tmp = target_db.with_name(target_db.name + ".copying")
    try:
        _copy_database(source, tmp)
        os.replace(tmp, target_db)
        prefs_old, prefs_new = source.with_name("preferences.json"), target_db.with_name("preferences.json")
        if prefs_old.is_file() and not prefs_new.exists():
            shutil.copy2(prefs_old, prefs_new)
    except Exception:  # noqa: BLE001 - best effort: the app starts fresh instead
        log.warning("Couldn't copy your data from %s to %s; starting with an empty database", source.parent, target_db.parent, exc_info=True)
        tmp.unlink(missing_ok=True)
        return None
    log.info("Copied your data from %s to %s; the old files were left in place", source.parent, target_db.parent)
    LAST_MIGRATION = source.parent
    return source.parent


def _copy_database(source: Path, dest: Path) -> None:
    """A consistent copy through SQLite's backup API: changes still in the source's -wal
    file are included, so the -wal and -shm files need no copying of their own."""
    dest.unlink(missing_ok=True)
    src = sqlite3.connect(source)
    try:
        src.execute("PRAGMA schema_version").fetchone()   # fails early on a file that isn't a database
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


__all__ = ["LAST_MIGRATION", "legacy_folders", "migrate_legacy_data", "prepare_data_dir"]
