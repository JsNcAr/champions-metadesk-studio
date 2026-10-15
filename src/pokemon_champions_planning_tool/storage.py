"""The data folder: create it, bring a packaged build's older data into it, back it up
and restore it.

Earlier packaged builds on Windows and Linux kept their files in whatever folder they were
started from. A packaged build now uses the per-user folder (``config.user_data_dir``); the first launch
copies the database and preferences found in the old place. The old files are left where
they are, so nothing is lost if the copy goes wrong.

A backup is one zip: a consistent copy of the database, preferences.json and a manifest.
A restore is staged (checked and unpacked into ``restore-pending/``) and applied at the next
launch, before anything opens the database, after a safety backup of the data it replaces.
Standard library only.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, config

log = logging.getLogger(__name__)

# The folder the data was copied from on this launch (for a one-time notice), or None.
LAST_MIGRATION: Path | None = None
# The backup restored on this launch (for a one-time notice), or None.
LAST_RESTORE: "BackupInfo | None" = None

BACKUP_PREFIX = "ChampionsMetaDesk-backup-"
DB_MEMBER, PREFS_MEMBER, MANIFEST_MEMBER = "pokemon_champions.db", "preferences.json", "manifest.json"
AUTO_BACKUPS_KEPT = 5


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


# -- backup and restore -------------------------------------------------------------------


class BackupError(Exception):
    """A backup can't be made, read or restored; the message is meant for the user."""


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    version: str           # the app version that made it
    schema: int            # PRAGMA user_version of its database
    created_at: datetime | None
    size: int              # bytes of the zip
    has_preferences: bool
    saved_to: Path | None = None   # after a restore: the safety backup of the data it replaced


def data_folder() -> Path:
    return Path(config.DEFAULT_DATABASE_FILENAME).resolve().parent


def auto_backup_folder() -> Path:
    """Where the app's own backups go (before a restore, before a schema upgrade)."""
    return data_folder() / "backups"


def _pending_folder() -> Path:
    return data_folder() / "restore-pending"


def _schema_of(db: Path) -> int:
    con = sqlite3.connect(db)
    try:
        return int(con.execute("PRAGMA user_version").fetchone()[0])
    finally:
        con.close()


def _free_name(folder: Path, stem: str) -> Path:
    path, n = folder / f"{stem}.zip", 2
    while path.exists():
        path, n = folder / f"{stem}-{n}.zip", n + 1
    return path


def create_backup(
    dest_dir: str | os.PathLike[str] | None = None, *, reason: str = "",
    database: str | os.PathLike[str] | None = None, preferences: str | os.PathLike[str] | None = None,
) -> Path:
    """Write ``ChampionsMetaDesk-backup-<date>-<time>[-reason].zip`` with a consistent copy of
    the database, preferences.json and a manifest. Written to a ``.partial`` file first, so
    a failed backup leaves nothing that looks complete. Returns its path."""
    db = Path(database or config.DEFAULT_DATABASE_FILENAME).resolve()
    prefs = Path(preferences or config.DEFAULT_PREFERENCES_FILENAME).resolve()
    if not db.is_file():
        raise BackupError("There is no data to back up yet")
    folder = Path(dest_dir if dest_dir is not None else config.EXPORT_DIR).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    target = _free_name(folder, BACKUP_PREFIX + now.astimezone().strftime("%Y%m%d-%H%M%S") + (f"-{reason}" if reason else ""))
    partial = target.with_name(target.name + ".partial")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / DB_MEMBER
        _copy_database(db, copy)
        manifest = {"app": config.APP_NAME, "version": __version__, "schema": _schema_of(copy),
                    "created_at": now.isoformat(), "reason": reason}
        try:
            with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(copy, DB_MEMBER)
                if prefs.is_file():
                    zf.write(prefs, PREFS_MEMBER)
                zf.writestr(MANIFEST_MEMBER, json.dumps(manifest, indent=2))
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
    log.info("Backup written to %s", target)
    return target


def _read_backup(path: Path, into: Path) -> BackupInfo:
    """Check a backup and unpack its files into ``into`` (only the known members, so a
    crafted zip can't write elsewhere). Raises ``BackupError``."""
    from .infrastructure.database.database import CURRENT_SCHEMA_VERSION

    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if MANIFEST_MEMBER not in names or DB_MEMBER not in names:
                raise BackupError("This zip isn't a Champions MetaDesk backup (its database or manifest is missing)")
            manifest = json.loads(zf.read(MANIFEST_MEMBER))
            if not isinstance(manifest, dict) or manifest.get("app") != config.APP_NAME:
                raise BackupError("This zip isn't a Champions MetaDesk backup")
            into.mkdir(parents=True, exist_ok=True)
            (into / DB_MEMBER).write_bytes(zf.read(DB_MEMBER))
            has_prefs = PREFS_MEMBER in names
            if has_prefs:
                (into / PREFS_MEMBER).write_bytes(zf.read(PREFS_MEMBER))
    except (zipfile.BadZipFile, OSError, ValueError, KeyError) as exc:
        raise BackupError(f"Can't read the backup: {exc}") from exc
    try:
        con = sqlite3.connect(into / DB_MEMBER)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            schema = int(con.execute("PRAGMA user_version").fetchone()[0])
        finally:
            con.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"The backup's database is damaged: {exc}") from exc
    if ok != "ok":
        raise BackupError(f"The backup's database is damaged: {ok}")
    if schema > CURRENT_SCHEMA_VERSION:
        raise BackupError(f"This backup was made by a newer version ({manifest.get('version', '?')}); update the app, then restore it")
    try:
        created = datetime.fromisoformat(str(manifest.get("created_at")))
    except ValueError:
        created = None
    return BackupInfo(path=path, version=str(manifest.get("version") or "?"), schema=schema, created_at=created,
                      size=path.stat().st_size, has_preferences=has_prefs)


def inspect_backup(path: str | os.PathLike[str]) -> BackupInfo:
    """What a backup holds, after checking it can be restored. Raises ``BackupError``."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise BackupError(f"No file at {path}")
    with tempfile.TemporaryDirectory() as tmp:
        return _read_backup(path, Path(tmp))


def stage_restore(path: str | os.PathLike[str]) -> BackupInfo:
    """Check a backup and unpack it into ``restore-pending/`` for the next launch to apply.
    The manifest is written last: a folder without it is an unfinished stage and is ignored."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise BackupError(f"No file at {path}")
    pending = _pending_folder()
    partial = pending.with_name(pending.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    try:
        info = _read_backup(path, partial)
        (partial / MANIFEST_MEMBER).write_text(json.dumps({"source": str(path), "version": info.version, "schema": info.schema,
                                                           "created_at": info.created_at.isoformat() if info.created_at else None}),
                                               encoding="utf-8")
        shutil.rmtree(pending, ignore_errors=True)
        os.replace(partial, pending)
    finally:
        shutil.rmtree(partial, ignore_errors=True)
    log.info("Restore of %s staged; it is applied at the next launch", path)
    return info


def pending_restore() -> dict | None:
    """The staged restore waiting for the next launch, or None."""
    marker = _pending_folder() / MANIFEST_MEMBER
    try:
        return json.loads(marker.read_text(encoding="utf-8")) if marker.is_file() else None
    except (OSError, ValueError):
        return None


def cancel_pending_restore() -> None:
    shutil.rmtree(_pending_folder(), ignore_errors=True)


def apply_pending_restore(
    *, database: str | os.PathLike[str] | None = None, preferences: str | os.PathLike[str] | None = None,
) -> BackupInfo | None:
    """Apply a staged restore. Call before anything opens the database. The data it
    replaces is backed up first; if that or anything else fails, the current data stays and
    the staged folder is renamed ``restore-failed-<time>``. Never raises."""
    global LAST_RESTORE
    meta = pending_restore()
    if meta is None:
        return None
    pending = _pending_folder()
    db = Path(database or config.DEFAULT_DATABASE_FILENAME).resolve()
    prefs = Path(preferences or config.DEFAULT_PREFERENCES_FILENAME).resolve()
    try:
        saved_to = create_backup(auto_backup_folder(), reason="before-restore", database=db, preferences=prefs) if db.is_file() else None
        if db.is_file():
            _checkpoint(db)
        for sidecar in (db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")):
            sidecar.unlink(missing_ok=True)   # a stale -wal would be replayed into the restored file
        os.replace(pending / DB_MEMBER, db)
        if (pending / PREFS_MEMBER).is_file():
            os.replace(pending / PREFS_MEMBER, prefs)
        else:
            prefs.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - the app must start whatever happens here
        failed = pending.with_name(f"restore-failed-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        log.error("Restoring the backup failed; your data was not changed. The staged files are in %s", failed, exc_info=True)
        try:
            os.replace(pending, failed)
        except OSError:
            shutil.rmtree(pending, ignore_errors=True)
        return None
    shutil.rmtree(pending, ignore_errors=True)
    if saved_to is not None:
        prune_backups(auto_backup_folder())
    try:
        created = datetime.fromisoformat(meta["created_at"]) if meta.get("created_at") else None
    except (TypeError, ValueError):
        created = None
    info = BackupInfo(path=Path(str(meta.get("source") or "")), version=str(meta.get("version") or "?"), schema=int(meta.get("schema") or 0),
                      created_at=created, size=0, has_preferences=prefs.is_file(), saved_to=saved_to)
    log.info("Restored the backup %s (made by %s); the previous data was saved to %s", info.path, info.version, saved_to)
    LAST_RESTORE = info
    return info


def _checkpoint(db: Path) -> None:
    """Fold the -wal into the database file, so nothing is lost when the sidecars go."""
    con = sqlite3.connect(db)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()


def backup_before_upgrade(database: str | os.PathLike[str] | None = None) -> Path | None:
    """Back the data up before a newer app migrates its schema. Best effort, never raises."""
    from .infrastructure.database.database import CURRENT_SCHEMA_VERSION

    db = Path(database or config.DEFAULT_DATABASE_FILENAME).resolve()
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect(db)
        try:
            schema = int(con.execute("PRAGMA user_version").fetchone()[0])
            has_tables = con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone() is not None
        finally:
            con.close()
        if not has_tables or schema >= CURRENT_SCHEMA_VERSION:
            return None
        path = create_backup(db.parent / "backups", reason=f"before-upgrade-v{schema}", database=db)
        prune_backups(db.parent / "backups")
        return path
    except Exception:  # noqa: BLE001 - an upgrade still runs without its safety copy
        log.warning("Couldn't back up the data before upgrading it", exc_info=True)
        return None


def prune_backups(folder: str | os.PathLike[str], keep: int = AUTO_BACKUPS_KEPT) -> None:
    """Keep the newest ``keep`` backups in the app's own backup folder."""
    backups = sorted(Path(folder).glob(f"{BACKUP_PREFIX}*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)


def list_backups(folders: Iterable[Path] | None = None) -> list[Path]:
    """Backups in the export folder (Back up now) and the app's own folder, newest first."""
    seen: dict[Path, None] = {}
    for folder in (folders if folders is not None else (Path(config.EXPORT_DIR), auto_backup_folder())):
        if Path(folder).is_dir():
            for path in Path(folder).glob(f"{BACKUP_PREFIX}*.zip"):
                seen[path.resolve()] = None
    return sorted(seen, key=lambda p: p.stat().st_mtime, reverse=True)


__all__ = [
    "BackupError", "BackupInfo", "LAST_MIGRATION", "LAST_RESTORE", "apply_pending_restore", "auto_backup_folder",
    "backup_before_upgrade", "cancel_pending_restore", "create_backup", "data_folder", "inspect_backup", "legacy_folders",
    "list_backups", "migrate_legacy_data", "pending_restore", "prepare_data_dir", "prune_backups", "stage_restore",
]
