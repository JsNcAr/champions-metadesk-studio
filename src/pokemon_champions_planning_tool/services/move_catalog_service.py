"""Move catalogue sync and loading: Showdown moves + Champions learnsets into SQLite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from ..config import MOVE_CATALOG_MAX_AGE_DAYS
from ..domain.moves import MoveInfo
from ..infrastructure.database.models import MoveRecord
from ..infrastructure.database.repositories import MoveRepository
from ..infrastructure.providers.showdown_moves_provider import ShowdownMovesNetworkError, ShowdownMovesProvider


def move_catalog_is_stale(session: Session, max_age_days: int = MOVE_CATALOG_MAX_AGE_DAYS) -> bool:
    repo = MoveRepository(session)
    meta = repo.get_meta()
    if meta is None or meta.move_count == 0 or meta.learnset_count == 0:
        return True
    synced = meta.last_synced_at
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced > timedelta(days=max_age_days)


def sync_move_catalog(session: Session, force: bool = False, provider: ShowdownMovesProvider | None = None) -> dict:
    """Fetch the three Showdown files and replace the local catalogue.

    Returns {"status": "synced"|"cached"|"offline", "moves": N, "learnsets": M, "species": S}.
    """
    repo = MoveRepository(session)
    if not force and not move_catalog_is_stale(session):
        meta = repo.get_meta()
        print(f"✅ Move catalogue up-to-date in local DB ({meta.move_count} moves, {meta.species_count} learnsets).")
        return {"status": "cached", "moves": meta.move_count, "learnsets": meta.learnset_count, "species": meta.species_count}
    try:
        payload = (provider or ShowdownMovesProvider()).fetch_move_catalog()
    except ShowdownMovesNetworkError as exc:
        print(f"⚠️ Move catalogue: {exc}. Keeping the local data.")
        meta = repo.get_meta()
        return {"status": "offline", "moves": meta.move_count if meta else 0, "learnsets": meta.learnset_count if meta else 0, "species": meta.species_count if meta else 0}
    records = [
        MoveRecord(move_id=m.move_id, name=m.name, type=m.type, category=m.category, power=m.power, accuracy=m.accuracy,
                   pp=m.pp, priority=m.priority, target=m.target, short_desc=m.short_desc, is_legal=m.is_legal)
        for m in payload.moves
    ]
    moves, pairs = repo.replace_all(records, {k: list(v) for k, v in payload.learnsets.items()})
    print(f"✅ Move catalogue synced: {moves} moves, {len(payload.learnsets)} learnsets ({pairs} pairs), {len(payload.removed)} removed in Champions.")
    return {"status": "synced", "moves": moves, "learnsets": pairs, "species": len(payload.learnsets), "removed": len(payload.removed)}


def sync_move_catalog_on_startup(session: Session) -> dict:
    """Startup hook: never raises; syncs only when missing or older than the max age."""
    try:
        return sync_move_catalog(session, force=False)
    except Exception as exc:  # noqa: BLE001 - startup must not depend on the network
        print(f"⚠️ Move catalogue check skipped: {exc}")
        return {"status": "error", "moves": 0, "learnsets": 0, "species": 0}


def load_move_catalog(session: Session) -> tuple[dict[str, MoveInfo], dict[str, frozenset[str]]]:
    """(moves by id, learnsets by species key) as immutable values for the UI catalogs."""
    repo = MoveRepository(session)
    moves = {
        r.move_id: MoveInfo(move_id=r.move_id, name=r.name, type=r.type, category=r.category, power=r.power, accuracy=r.accuracy,
                            pp=r.pp, priority=r.priority, target=r.target, short_desc=r.short_desc, is_legal=r.is_legal)
        for r in repo.list_moves()
    }
    learnsets = {k: frozenset(v) for k, v in repo.list_learnsets().items()}
    return moves, learnsets


__all__ = ["load_move_catalog", "move_catalog_is_stale", "sync_move_catalog", "sync_move_catalog_on_startup"]
