"""Move choices for one species: legal moves, every other move, and tournament usage.

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


def move_options_for(catalogs: Catalogs, canonical_id: str | None, session_factory: SessionFactory | None) -> MoveOptions:
    """Legal moves for a species (base form for megas), every other Champions move, and how
    often stored tournament rosters of that species carry each move."""
    if not canonical_id:
        return EMPTY_MOVE_OPTIONS
    legal_ids = catalogs.legal_move_ids(canonical_id)
    known = legal_ids is not None
    by_name = lambda m: m.name.lower()  # noqa: E731
    catalogue = [m for m in catalogs.moves_by_id.values() if m.is_legal]
    if known:
        legal = sorted((m for m in catalogue if m.move_id in legal_ids), key=by_name)
        others = sorted((m for m in catalogue if m.move_id not in legal_ids), key=by_name)
    else:
        legal, others = sorted(catalogue, key=by_name), []
    usage: dict[str, float] = {}
    if session_factory is not None:
        try:
            with session_factory() as s:
                usage = TournamentService(s).move_usage(base_canonical_id(canonical_id))
        except Exception:  # noqa: BLE001 - usage is a ranking hint, never required
            usage = {}
    return MoveOptions(tuple(legal), tuple(others), usage, known)
