"""Bulk and power benchmarks for one move of the calculation. Flet-free.

"OHKO needs Atk 20": the fewest attacking stat points for a guaranteed KO (the lowest roll)
in one or two hits. "Survives with HP 12 / Def 8": the fewest HP + defending stat points so
the defender takes the highest roll once (or twice) and lives. Nature, item, ability,
stages, the field and the spread-move rule are the calculation's own; only the points the
answer is about change, and the points already spent elsewhere count toward the 66.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from ....domain.species import SpeciesInfo
from ....domain.stat_calc import MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, champions_stats, points_total
from ....services.damage_calc_service import build_calc_move, calculate
from ...catalogs import Catalogs
from .state import SPREAD_TARGETS, CalcState, PokemonState
from .store import engine_field, engine_pokemon, run_side

# Moves that do not read the usual attacking or defending stat.
_ATTACKS_WITH = {"Body Press": "defense"}
_SKIP_KO = {"Foul Play"}                    # uses the target's Attack: no attacker points help
_HITS_DEFENSE = {"Psyshock", "Psystrike", "Secret Sword"}

STAT_SHORT = {"attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "hp": "HP"}


@dataclass(frozen=True)
class KoBenchmark:
    hits: int
    stat: str                   # the attacker's stat the points go into
    points: int | None          # None: not even with every point it can take
    current: int                # points in that stat now


@dataclass(frozen=True)
class SurviveBenchmark:
    hits: int
    stat: str                   # the defender's defending stat
    hp: int | None              # None: no spread survives
    defence: int | None
    current_hp: int
    current_defence: int


@dataclass(frozen=True)
class Benchmarks:
    move: str
    ko: tuple[KoBenchmark, ...] = ()
    survive: tuple[SurviveBenchmark, ...] = ()


def _cur_hp(p: PokemonState, species: SpeciesInfo) -> int:
    max_hp = champions_stats(species.stats, p.points, p.nature if p.nature != "hardy" else None).hp
    return max(1, min(max_hp, round(max_hp * p.hp_pct / 100)))


def _with_points(p: PokemonState, **points: int) -> PokemonState:
    new = dict(p.points)
    for stat, value in points.items():
        if value:
            new[stat] = value
        else:
            new.pop(stat, None)
    return replace(p, points=new)


def benchmarks(state: CalcState, side: str, index: int, catalogs: Catalogs, calc: Callable = calculate) -> Benchmarks | None:
    """KO and survival benchmarks for the move in ``side``'s slot ``index``; None when there
    is nothing to measure (no move, a status move, no species on either side)."""
    other = "right" if side == "left" else "left"
    attacker, defender = state.side(side), state.side(other)
    name = attacker.moves[index]
    a_species = catalogs.species_for(attacker.species)
    d_species = catalogs.species_for(defender.species)
    if not name or a_species is None or d_species is None:
        return None
    field = engine_field(state.field, attacker_is_left=(side == "left"))
    a_engine = engine_pokemon(attacker, a_species)
    move = build_calc_move(name, catalogs, attacker_ability=a_engine.ability or (a_engine.abilities[0] if a_engine.abilities else None),
                           is_crit=bool(attacker.crit[index]))
    if move is None or move.category == "Status":
        return None
    if field.game_type == "Doubles" and move.target in SPREAD_TARGETS and attacker.single[index]:
        move = replace(move, target="normal")
    solo = replace(attacker, moves=[name, None, None, None])
    prebuilt = [(move, name)]

    def hit(a: PokemonState, d: PokemonState, *, a_engine=None, d_engine=None):
        results = run_side(a, d, field, catalogs, calc, a_species, d_species, fast=True, a_engine=a_engine, d_engine=d_engine, prebuilt_moves=prebuilt)
        result = results[0] if results else None
        return result if result is not None and result.ok else None

    # -- power: the attacker's points for a guaranteed KO -----------------------------------
    ko: list[KoBenchmark] = []
    stat = _ATTACKS_WITH.get(name, "attack" if move.category == "Physical" else "special_attack")
    if name not in _SKIP_KO:
        d_engine = engine_pokemon(defender, d_species)
        target_hp = _cur_hp(defender, d_species)
        current = int(attacker.points.get(stat, 0))
        cap = min(MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL - (points_total(attacker.points) - current))
        for hits in (1, 2):
            def kos(points: int, hits=hits) -> bool:
                result = hit(_with_points(solo, **{stat: points}), defender, d_engine=d_engine)
                return result is not None and result.min_dmg * hits >= target_hp
            ko.append(KoBenchmark(hits, stat, _lowest(0, cap, kos), current))

    # -- bulk: the defender's HP + defence for surviving the highest roll --------------------
    survive: list[SurviveBenchmark] = []
    physical = move.category == "Physical" or name in _HITS_DEFENSE
    d_stat = "defense" if physical else "special_defense"
    cur_hp_pts, cur_def_pts = int(defender.points.get("hp", 0)), int(defender.points.get(d_stat, 0))
    budget = MAX_POINTS_TOTAL - (points_total(defender.points) - cur_hp_pts - cur_def_pts)
    for hits in (1, 2):
        best: tuple[int, int] | None = None
        for hp in range(0, min(MAX_POINTS_PER_STAT, budget) + 1):
            if best is not None and hp > sum(best):
                break   # no smaller total can come from more HP alone

            def lives(points: int, hp=hp, hits=hits) -> bool:
                d = _with_points(defender, **{"hp": hp, d_stat: points})
                result = hit(solo, d, a_engine=a_engine)
                return result is None or result.max_dmg * hits < _cur_hp(d, d_species)
            cap = min(MAX_POINTS_PER_STAT, budget - hp)
            points = _lowest(0, cap, lives)
            if points is None:
                continue
            if best is None or hp + points < sum(best) or (hp + points == sum(best) and hp > best[0]):
                best = (hp, points)
        survive.append(SurviveBenchmark(hits, d_stat, best[0] if best else None, best[1] if best else None, cur_hp_pts, cur_def_pts))
    return Benchmarks(name, tuple(ko), tuple(survive))


def _lowest(lo: int, hi: int, ok: Callable[[int], bool]) -> int | None:
    """The smallest value in [lo, hi] for which ``ok`` holds (``ok`` is monotonic); None if none."""
    if hi < lo or not ok(hi):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def ko_text(b: KoBenchmark) -> str:
    """Reads after "You": "OHKO with Atk 20", "2HKO with no points", "can't OHKO"."""
    label = "OHKO" if b.hits == 1 else f"{b.hits}HKO"
    if b.points is None:
        return f"can't {label}"
    if b.points == 0:
        return f"{label} with no points"
    return f"{label} with {STAT_SHORT[b.stat]} {b.points}"


def survive_text(b: SurviveBenchmark) -> str:
    """Reads after "They": "survive 1 hit with HP 12 / Def 8", "can't survive 2 hits"."""
    label = "1 hit" if b.hits == 1 else f"{b.hits} hits"
    if b.hp is None:
        return f"can't survive {label}"
    if b.hp == 0 and b.defence == 0:
        return f"survive {label} with no points"
    return f"survive {label} with HP {b.hp} / {STAT_SHORT[b.stat]} {b.defence}"


def ko_needs_points(b: KoBenchmark) -> bool:
    """Apply is offered only when the KO needs more than what is spent now."""
    return b.points is not None and b.points > b.current


def survive_needs_points(b: SurviveBenchmark) -> bool:
    return b.hp is not None and b.defence is not None and (b.hp > b.current_hp or b.defence > b.current_defence)


__all__ = ["Benchmarks", "KoBenchmark", "STAT_SHORT", "SurviveBenchmark", "benchmarks", "ko_needs_points", "ko_text", "survive_needs_points", "survive_text"]
