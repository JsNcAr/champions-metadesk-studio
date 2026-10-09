"""Damage for the battle flow: each attack you picked against the foe(s) it targets. Pure.

The attacker is the team member on that slot at that turn (``flow.board_at``), in the form
it has then: the base form until the turn it Mega Evolves, the Mega form from that turn on.
Each attack is the calculator's full single-move calc (damage range and KO chance) under
the plan's field; a spread move against both foes takes the Doubles ×0.75, against one foe
none. Cached by the two sets, the field and the move, like the grid.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..calc.state import MoveResult, PokemonState
from ..calc.store import engine_field, run_side
from .flow import Scenario, Where, board_at, foes_at
from .grid import calc_key, remember
from .model import Plan

HitKey = tuple[Where, int, int]   # (branch or None, turn index in its line, your slot)


@dataclass(frozen=True)
class Hit:
    foe_index: int
    result: MoveResult


def _base_and_mega(state: PokemonState, catalogs: Any) -> tuple[str | None, str | None]:
    species = catalogs.species_for(state.species) if state.species else None
    if species is None:
        return state.species, None
    base = species.base_species_id if species.is_mega else species.canonical_id
    return base, catalogs.mega_for_item(base, state.item)


def can_mega(state: PokemonState | None, catalogs: Any) -> bool:
    """Holds the Mega Stone for its species."""
    return state is not None and _base_and_mega(state, catalogs)[1] is not None


def form_for(state: PokemonState, *, mega_now: bool, catalogs: Any) -> PokemonState:
    """The member as it is on the field: its Mega form once it has Mega Evolved, its base
    form before (a member saved as its Mega form in Teams is shown as the base until then).
    The form's first ability is used when the form changes."""
    base, mega = _base_and_mega(state, catalogs)
    if mega is None:
        return state
    target = mega if mega_now else base
    if target == state.species or target is None:
        return state
    species = catalogs.species_for(target)
    ability = species.abilities[0] if species is not None and species.abilities else state.ability
    return replace(state, species=target, ability=ability)


def _one(attacker: PokemonState, index: int, defender: PokemonState, *, single: bool, plan: Plan, catalogs: Any) -> MoveResult | None:
    only = replace(attacker, moves=[m if j == index else None for j, m in enumerate(attacker.moves)],
                   single=[single if j == index else False for j in range(4)])
    results = run_side(only, defender, engine_field(plan.field, attacker_is_left=True), catalogs)
    return results[0] if results else None


def action_hits(plan: Plan, sc: Scenario, mine: dict[str, PokemonState], catalogs: Any, *, cache: dict | None = None) -> dict[HitKey, tuple[Hit, ...]]:
    """Every picked attack of a scenario (main line and "If…" branches) against its target(s)."""
    out: dict[HitKey, tuple[Hit, ...]] = {}
    lines: list[Where] = [None, *range(len(sc.branches))]
    for where in lines:
        for i, turn in enumerate(sc.turns_of(where)):
            board = None
            for slot, action in enumerate(turn.actions):
                if action.kind != "move" or not action.move or action.target not in ("foe", "foes"):
                    continue
                board = board or board_at(plan, sc, i, where)
                who = board.slot(slot)
                state = mine.get(who.box_entry_id) if who is not None else None
                if state is None:
                    continue
                attacker = form_for(state, mega_now=action.mega or board.mega_by == who.box_entry_id, catalogs=catalogs)
                if action.move not in attacker.moves:
                    continue
                index = attacker.moves.index(action.move)
                if action.target == "foe":
                    targets = [action.foe] if action.foe is not None else []
                else:
                    targets = list(foes_at(sc, i, where))
                targets = [t for t in targets if 0 <= t.index < len(plan.opponent)]
                single = action.target == "foe" or len(targets) == 1
                hits: list[Hit] = []
                for foe in targets:
                    defender = plan.opponent[foe.index].pokemon
                    key = calc_key(attacker, defender, plan.field, f"flow:{action.move}:{single}")
                    result = cache.get(key) if cache is not None else None
                    if result is None:
                        result = _one(attacker, index, defender, single=single, plan=plan, catalogs=catalogs)
                        if result is not None:
                            remember(cache, key, result)
                    if result is not None and result.ok:
                        hits.append(Hit(foe.index, result))
                if hits:
                    out[(where, i, slot)] = tuple(hits)
    return out


def hit_text(hits: tuple[Hit, ...], foe_name: Any) -> str:
    """"92–109% · 50% chance to OHKO", or one part per foe for a spread move."""
    def one(hit: Hit) -> str:
        r = hit.result
        return f"{r.min_pct:g}–{r.max_pct:g}%" + (f" · {r.ko_text}" if r.ko_text else "")
    if len(hits) == 1:
        return one(hits[0])
    return " / ".join(f"{foe_name(h.foe_index)} {one(h)}" for h in hits)


__all__ = ["Hit", "HitKey", "action_hits", "can_mega", "form_for", "hit_text"]
