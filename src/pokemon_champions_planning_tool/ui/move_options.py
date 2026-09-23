"""Move and item choices for one species: legal moves, every other move, and tournament usage.

Flet-free and store-independent so the team builder and the damage calculator share it.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass

from sqlmodel import Session

from ..domain.moves import MoveInfo, base_canonical_id
from ..services.tournament_service import TournamentService
from .catalogs import Catalogs

SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True)
class MoveOptions:
    legal: tuple[MoveInfo, ...]
    others: tuple[MoveInfo, ...]
    usage: dict[str, float]     # move id -> share of that species' tournament rosters
    known: bool                 # False: the catalogue has no learnset for this species


EMPTY_MOVE_OPTIONS = MoveOptions((), (), {}, False)

# Roster usage per base species. The query reads every roster row of that species, which
# costs tens of milliseconds on a year of data, and the answer only changes when
# tournament data does — so it is kept until ``invalidate_move_usage()`` says otherwise.
_usage_cache: dict[str, dict[str, float]] = {}
_item_usage_cache: dict[str, dict[str, float]] = {}


def invalidate_move_usage() -> None:
    """New tournament data landed: re-read move and item usage on the next request."""
    _usage_cache.clear()
    _item_usage_cache.clear()


def item_usage_for(catalogs: Catalogs, canonical_id: str | None, session_factory: SessionFactory | None) -> dict[str, float]:
    """{item catalogue id: share of this species' tournament rosters holding it} (megas count
    for their base species). Blocking the first time per species: call it off the UI loop."""
    if not canonical_id or session_factory is None:
        return {}
    base_id = base_canonical_id(canonical_id)
    cached = _item_usage_cache.get(base_id)
    if cached is not None:
        return cached
    try:
        with session_factory() as s:
            by_name = TournamentService(s).item_usage(base_id)
    except Exception:  # noqa: BLE001 - usage is a ranking hint, never required
        return {}
    usage: dict[str, float] = {}
    for name, share in by_name.items():
        record = catalogs.item_for(name) or catalogs.item_for(name.lower().replace(" ", "-"))
        if record is not None:
            usage[record.canonical_id] = usage.get(record.canonical_id, 0.0) + share
    _item_usage_cache[base_id] = usage
    return usage


def _usage_for(base_id: str, session_factory: SessionFactory | None) -> dict[str, float]:
    if session_factory is None:
        return {}
    cached = _usage_cache.get(base_id)
    if cached is not None:
        return cached
    try:
        with session_factory() as s:
            usage = TournamentService(s).move_usage(base_id)
    except Exception:  # noqa: BLE001 - usage is a ranking hint, never required
        return {}
    _usage_cache[base_id] = usage
    return usage


def move_options_for(catalogs: Catalogs, canonical_id: str | None, session_factory: SessionFactory | None) -> MoveOptions:
    """Legal moves for a species (base form for megas), every other Champions move, and how
    often stored tournament rosters of that species carry each move."""
    if not canonical_id:
        return EMPTY_MOVE_OPTIONS
    legal_ids = catalogs.legal_move_ids(canonical_id)
    known = legal_ids is not None
    # Pre-sorted once per catalogue: the picker only has to split it in two.
    catalogue = catalogs.legal_moves_sorted
    if known:
        legal = tuple(m for m in catalogue if m.move_id in legal_ids)
        others = tuple(m for m in catalogue if m.move_id not in legal_ids)
    else:
        legal, others = catalogue, ()
    return MoveOptions(legal, others, _usage_for(base_canonical_id(canonical_id), session_factory), known)
