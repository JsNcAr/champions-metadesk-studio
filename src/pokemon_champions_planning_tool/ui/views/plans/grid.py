"""A plan's matchup grid: your six against their six under the plan's field. Pure.

Two passes, as cheap as possible. ``compute_grid`` rates every pairing in the calculator's
fast mode (best hit each way, speeds, the Crushed / Threat / … class) like Calc's Team vs
team grid. ``with_ko_text`` then runs the full calculation, which is what writes "guaranteed
2HKO", on the winning move of each direction only: 72 single-move calcs for a full grid
instead of every move of every pairing. Both are cached by the two sets and the field, so
editing a note, or reopening a plan, recomputes nothing.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, replace
from typing import Any

from ..calc.state import FieldState, MoveResult, PokemonState, TeamRating
from ..calc.store import engine_field, matchup, run_side

Grid = dict[tuple[str, int], TeamRating]   # (your box entry id, their index) -> rating

_IGNORED = ("source", "assumptions")
_CACHE_LIMIT = 1024


def _key(you: PokemonState, rival: PokemonState, field: FieldState, kind: str) -> str:
    y = {k: v for k, v in asdict(you).items() if k not in _IGNORED}
    r = {k: v for k, v in asdict(rival).items() if k not in _IGNORED}
    return json.dumps((kind, y, r, asdict(field)), sort_keys=True, default=str)


def _remember(cache: dict | None, key: str, value: Any) -> None:
    if cache is None:
        return
    if len(cache) >= _CACHE_LIMIT:
        cache.clear()
    cache[key] = value


def compute_grid(mine: Sequence[tuple[str, PokemonState]], opponent: Sequence[PokemonState], field: FieldState, catalogs: Any,
                 *, cache: dict | None = None) -> Grid:
    """Every pairing, fast mode: your best hit, theirs, both speeds, who moves first and the
    class, from your side. A pairing with a species missing from the catalogue is left out."""
    fields = (engine_field(field, attacker_is_left=True), engine_field(field, attacker_is_left=False))
    grid: Grid = {}
    for box_id, you in mine:
        y_species = catalogs.species_for(you.species) if you.species else None
        if y_species is None:
            continue
        for j, rival in enumerate(opponent):
            r_species = catalogs.species_for(rival.species) if rival.species else None
            if r_species is None:
                continue
            key = _key(you, rival, field, "fast")
            cached = cache.get(key) if cache is not None else None
            if cached is None:
                yours, theirs, y_speed, r_speed, faster, klass = matchup(you, y_species, rival, r_species, field, catalogs, fields=fields)
                cached = TeamRating(box_id, r_species.name, klass, yours, theirs, y_speed, r_speed, faster)
                _remember(cache, key, cached)
            grid[(box_id, j)] = replace(cached, slot_key=box_id)
    return grid


def _full(attacker: PokemonState, defender: PokemonState, best: MoveResult | None, field: FieldState, catalogs: Any, *, left: bool) -> MoveResult | None:
    """The best move again in full mode (description and KO text), alone in the move list so
    nothing else is calculated."""
    if best is None:
        return None
    only = replace(attacker, moves=[name if i == best.index else None for i, name in enumerate(attacker.moves)])
    results = run_side(only, defender, engine_field(field, attacker_is_left=left), catalogs)
    return results[0] if results and results[0].ok else best


def with_ko_text(grid: Grid, mine: Sequence[tuple[str, PokemonState]], opponent: Sequence[PokemonState], field: FieldState, catalogs: Any,
                 *, cache: dict | None = None) -> Grid:
    """The grid with KO text ("guaranteed 2HKO", "52.3% chance to OHKO") on each best hit."""
    yours_by_id = dict(mine)
    out: Grid = {}
    for (box_id, j), rating in grid.items():
        you, rival = yours_by_id.get(box_id), opponent[j] if j < len(opponent) else None
        if you is None or rival is None:
            out[(box_id, j)] = rating
            continue
        key = _key(you, rival, field, "ko")
        cached = cache.get(key) if cache is not None else None
        if cached is None:
            cached = replace(
                rating,
                your_best=_full(you, rival, rating.your_best, field, catalogs, left=True),
                their_best=_full(rival, you, rating.their_best, field, catalogs, left=False),
            )
            _remember(cache, key, cached)
        out[(box_id, j)] = replace(cached, slot_key=box_id)
    return out


__all__ = ["Grid", "compute_grid", "with_ko_text"]
