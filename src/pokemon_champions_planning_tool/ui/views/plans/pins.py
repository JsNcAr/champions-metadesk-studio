"""Pinned calcs: a saved calculator state, recomputed each time it is shown. Pure.

A pin keeps the whole situation it was saved in: boosts, HP, status, crits, active
status moves, a spread move's single target, and the field. Its two sides can be linked to
the team member and the plan's opponent they stand for; recomputing then takes their
current sets (item, ability, nature, points, moves) so the line follows a spread or item
change, and keeps the situation as saved. An unlinked side stays exactly as pinned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from ..calc.hit import hit_text
from ..calc.state import CalcResults, CalcState, MoveResult, PokemonState
from ..calc.store import best_of, run
from .model import PinnedCalc

# What a link replaces: the set. The rest of PokemonState is the situation and stays.
SET_FIELDS = ("species", "nature", "points", "ability", "item", "moves")


@dataclass(frozen=True)
class PinView:
    """A pin as it reads now: its lines, and the state they were computed from."""

    pin: PinnedCalc
    state: CalcState
    lines: tuple[str, ...]
    your_name: str = ""
    their_name: str = ""
    linked_yours: bool = False      # the link still finds its team member
    linked_theirs: bool = False
    broken: tuple[str, ...] = ()    # what a link could not find any more ("team member", "opponent")


def _with_set(situation: PokemonState, current: PokemonState) -> PokemonState:
    """``current``'s set on ``situation``'s boosts, HP, status, crits and the like. Move
    flags (crit, active, single) follow the move by slot, as in the calculator."""
    return replace(situation, **{f: getattr(current, f) for f in SET_FIELDS})


def resolve(pin: PinnedCalc, mine: dict[str, PokemonState], opponent: Sequence[PokemonState]) -> tuple[CalcState, bool, bool, tuple[str, ...]]:
    """The pin's state with its linked sides refreshed: (state, yours linked, theirs linked,
    links that no longer resolve)."""
    state = pin.state
    broken: list[str] = []
    yours_ok = theirs_ok = False
    if pin.link.box_entry_id:
        current = mine.get(pin.link.box_entry_id)
        if current is not None:
            state = state.with_side(pin.mine, _with_set(state.side(pin.mine), current))
            yours_ok = True
        else:
            broken.append("team member")
    if pin.link.opp_index is not None:
        if 0 <= pin.link.opp_index < len(opponent):
            state = state.with_side(pin.theirs, _with_set(state.side(pin.theirs), opponent[pin.link.opp_index]))
            theirs_ok = True
        else:
            broken.append("opponent")
    return state, yours_ok, theirs_ok, tuple(broken)


def _line(result: MoveResult | None, fallback: str) -> str:
    if result is None:
        return fallback
    return result.description or hit_text(result, fallback, ko=True)


def lines_for(results: CalcResults, pin: PinnedCalc) -> tuple[str, ...]:
    """The calc line(s) a pin shows: the focused move, or your best hit and theirs."""
    yours = results.left_vs_right if pin.mine == "left" else results.right_vs_left
    theirs = results.right_vs_left if pin.mine == "left" else results.left_vs_right
    if pin.focus is not None:
        side, index = pin.focus
        moves = results.left_vs_right if side == "left" else results.right_vs_left
        pinned = pin.state.side(side).moves
        name = pinned[index] if 0 <= index < len(pinned) else None
        # By name first: a linked set whose moves were reordered still shows the pinned move.
        hit = next((r for r in moves if name and r.name == name), None) or next((r for r in moves if r.index == index), None)
        if hit is not None:
            return (_line(hit, hit.name) if hit.ok else f"{hit.name}: {hit.error}",)
    return tuple(line for line in (_line(best_of(yours), ""), _line(best_of(theirs), "")) if line)


def view_pin(pin: PinnedCalc, mine: dict[str, PokemonState], opponent: Sequence[PokemonState], catalogs: Any) -> PinView:
    state, yours_ok, theirs_ok, broken = resolve(pin, mine, opponent)
    results = run(state, catalogs)
    names = {"left": results.left_name, "right": results.right_name}
    lines = lines_for(results, pin) or ("No damaging move on either side",)
    return PinView(pin, state, lines, names[pin.mine], names[pin.theirs], yours_ok, theirs_ok, broken)


__all__ = ["PinView", "SET_FIELDS", "lines_for", "resolve", "view_pin"]
