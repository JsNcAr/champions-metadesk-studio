"""Calculator store: state, mutations, results and persistence. Flet-free.

Every mutation recomputes both directions (eight engine calls, a few milliseconds), keeps the
result in a small cache keyed by the state, persists the state in the preferences and
notifies ``("state",)`` then ``("results",)``.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Any

from sqlmodel import Session

from ....domain.damage import CalcMove, Field, Side
from ....domain.damage.ko import DescError
from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.species import SpeciesInfo
from ....domain.stat_calc import MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, champions_stats, points_total
from ....infrastructure.database.database import get_session
from ....services.damage_calc_service import build_calc_move, calculate, pokemon_from_species
from ...catalogs import Catalogs
from ...move_options import EMPTY_MOVE_OPTIONS, MoveOptions, move_options_for
from .state import BOOST_STATS, SIDES, CalcRequest, CalcResults, CalcState, FieldState, MoveResult, PokemonState, SideConditions, pokemon_from_species_id

SessionFactory = Callable[[], AbstractContextManager[Session]]
Listener = Callable[[tuple], None]

PREF_STATE = "calc.state"


def _engine_side(c: SideConditions) -> Side:
    return Side(spikes=c.spikes, is_sr=c.stealth_rock, is_reflect=c.reflect, is_light_screen=c.light_screen, is_protected=c.protect, is_seeded=c.leech_seed,
                is_charge=c.charge, is_tailwind=c.tailwind, is_helping_hand=c.helping_hand, is_power_trick=c.power_trick, is_friend_guard=c.friend_guard, is_aurora_veil=c.aurora_veil)


def engine_field(f: FieldState, *, attacker_is_left: bool) -> Field:
    a, d = (f.left, f.right) if attacker_is_left else (f.right, f.left)
    return Field(game_type="Doubles" if f.game_type == "doubles" else "Singles", weather=None if f.weather == "none" else f.weather,
                 terrain=None if f.terrain == "none" else f.terrain, is_gravity=f.gravity, is_magic_room=f.magic_room, is_wonder_room=f.wonder_room,
                 attacker_side=_engine_side(a), defender_side=_engine_side(d))


def engine_pokemon(p: PokemonState, species: SpeciesInfo):
    max_hp = champions_stats(species.stats, p.points, p.nature if p.nature != "hardy" else None).hp
    cur = max(1, min(max_hp, round(max_hp * p.hp_pct / 100)))
    return pokemon_from_species(species, ability=p.ability, ability_on=p.ability_on, item=p.item, nature=p.nature, points=p.points, boosts=p.boosts,
                                cur_hp=cur, status="" if p.status == "none" else p.status, allies_fainted=p.allies_fainted)


def run_side(attacker: PokemonState, defender: PokemonState, field: Field, catalogs: Catalogs, calc: Callable = calculate) -> tuple[MoveResult, ...]:
    a_species = catalogs.species_for(attacker.species)
    d_species = catalogs.species_for(defender.species)
    if a_species is None or d_species is None:
        return ()
    a = engine_pokemon(attacker, a_species)
    d = engine_pokemon(defender, d_species)
    out: list[MoveResult] = []
    for index, name in enumerate(attacker.moves):
        if not name:
            continue
        move = build_calc_move(name, catalogs, attacker_ability=a.ability or (a.abilities[0] if a.abilities else None), is_crit=bool(attacker.crit[index]))
        if move is None:
            out.append(MoveResult(index, name, None, None, 0, 0, 0.0, 0.0, (), "", "", error="Not in the move catalogue"))
            continue
        if move.category == "Status":
            out.append(MoveResult(index, name, move.type, move.category, 0, 0, 0.0, 0.0, (), "", "", error="Status move"))
            continue
        try:
            result = calc(a, d, move, field)
            lo, hi = result.range()
            if hi == 0:
                out.append(MoveResult(index, name, result.move.type, move.category, 0, 0, 0.0, 0.0, (), "", "", error="No effect", bp=result.move_bp))
                continue
            try:
                description = result.desc()
                ko_text = result.ko_chance().text
            except DescError:
                description, ko_text = "", ""
            recoil_text = result.recoil()[1] or None
            recovery_text = result.recovery()[1] or None
            out.append(MoveResult(index, name, result.move.type, move.category, lo, hi, result.min_pct, result.max_pct, tuple(result.rolls), description, ko_text,
                                  recoil_text, recovery_text, bp=result.move_bp))
        except Exception as exc:  # noqa: BLE001 - one bad move must not hide the others
            out.append(MoveResult(index, name, move.type, move.category, 0, 0, 0.0, 0.0, (), "", "", error=f"{type(exc).__name__}: {exc}"))
    return tuple(out)


def run(state: CalcState, catalogs: Catalogs, calc: Callable = calculate) -> CalcResults:
    left = catalogs.species_for(state.left.species)
    right = catalogs.species_for(state.right.species)
    return CalcResults(
        left_vs_right=run_side(state.left, state.right, engine_field(state.field, attacker_is_left=True), catalogs, calc),
        right_vs_left=run_side(state.right, state.left, engine_field(state.field, attacker_is_left=False), catalogs, calc),
        left_name=left.name if left else "", right_name=right.name if right else "",
    )


class CalcStore:
    def __init__(self, catalogs: Catalogs | None = None, session_factory: SessionFactory | None = get_session, *, prefs: Any = None, calculate_fn: Callable | None = None) -> None:
        self.catalogs = catalogs or Catalogs()
        self._sf = session_factory
        self._prefs = prefs
        self._calc = calculate_fn or calculate
        self.state = CalcState()
        self.results = CalcResults()
        self._cache: OrderedDict[str, CalcResults] = OrderedDict()
        self._listeners: list[Listener] = []
        self.loaded = False

    # -- subscriptions -----------------------------------------------------------------------

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    def _notify(self, event: tuple) -> None:
        for listener in list(self._listeners):
            listener(event)

    # -- loading -----------------------------------------------------------------------------

    def load(self) -> None:
        """Restore the last calculation from the preferences (once)."""
        if self.loaded:
            return
        self.loaded = True
        if self._prefs is not None:
            try:
                self.state = CalcState.from_dict(self._prefs.get(PREF_STATE, None))
            except Exception:  # noqa: BLE001 - a corrupt preference must not break the view
                self.state = CalcState()
        self._recompute(persist=False)

    def apply_request(self, req: CalcRequest) -> None:
        if req.attacker is not None:
            self.state = self.state.with_side("left", req.attacker)
        if req.defender is not None:
            self.state = self.state.with_side("right", req.defender)
        self._commit()

    def load_species(self, side: str, canonical_id: str) -> None:
        species = self.catalogs.species_for(canonical_id)
        self.state = self.state.with_side(side, pokemon_from_species_id(species.canonical_id if species else canonical_id, species))
        self._commit()

    def load_pokemon(self, side: str, pokemon: PokemonState) -> None:
        self.state = self.state.with_side(side, pokemon)
        self._commit()

    # -- readers -----------------------------------------------------------------------------

    def species(self, side: str) -> SpeciesInfo | None:
        return self.catalogs.species_for(self.state.side(side).species)

    def stats(self, side: str) -> PokemonStats | None:
        species = self.species(side)
        if species is None:
            return None
        p = self.state.side(side)
        try:
            return champions_stats(species.stats, p.points, p.nature)
        except ValueError:
            return champions_stats(species.stats, p.points, None)

    def max_hp(self, side: str) -> int:
        stats = self.stats(side)
        return stats.hp if stats else 0

    def cur_hp(self, side: str) -> int:
        max_hp = self.max_hp(side)
        return max(1, min(max_hp, round(max_hp * self.state.side(side).hp_pct / 100))) if max_hp else 0

    def ability_options(self, side: str) -> list[str]:
        species = self.species(side)
        options = list(species.abilities) if species else []
        current = self.state.side(side).ability
        if current and current not in options:
            options.append(current)
        return options

    def move_options(self, side: str) -> MoveOptions:
        species = self.species(side)
        if species is None:
            return EMPTY_MOVE_OPTIONS
        return move_options_for(self.catalogs, species.canonical_id, self._sf)

    def search_species(self, query: str) -> list[SpeciesInfo]:
        return self.catalogs.search_species(query)

    def points_left(self, side: str) -> int:
        return MAX_POINTS_TOTAL - points_total(self.state.side(side).points)

    # -- mutations ---------------------------------------------------------------------------

    def set_pokemon(self, side: str, **changes: Any) -> None:
        self.state = self.state.with_side(side, replace(self.state.side(side), **changes))
        self._commit()

    def set_nature(self, side: str, nature: str | None) -> None:
        self.set_pokemon(side, nature=(nature or "hardy").lower())

    def set_points(self, side: str, points: dict[str, int]) -> None:
        clean = {k: max(0, min(MAX_POINTS_PER_STAT, int(v))) for k, v in points.items() if int(v) > 0}
        self.set_pokemon(side, points=clean)

    def set_boost(self, side: str, stat: str, value: int) -> None:
        if stat not in BOOST_STATS:
            return
        boosts = dict(self.state.side(side).boosts)
        value = max(-6, min(6, int(value)))
        if value:
            boosts[stat] = value
        else:
            boosts.pop(stat, None)
        self.set_pokemon(side, boosts=boosts)

    def set_hp_pct(self, side: str, pct: float) -> None:
        self.set_pokemon(side, hp_pct=max(0.0, min(100.0, float(pct))))

    def set_hp_abs(self, side: str, hp: int) -> None:
        max_hp = self.max_hp(side)
        if max_hp:
            self.set_hp_pct(side, 100.0 * max(1, min(max_hp, int(hp))) / max_hp)

    def set_move(self, side: str, index: int, name: str | None) -> None:
        moves = list(self.state.side(side).moves)
        moves[index] = (name or "").strip() or None
        self.set_pokemon(side, moves=moves)

    def toggle_crit(self, side: str, index: int) -> None:
        crit = list(self.state.side(side).crit)
        crit[index] = not crit[index]
        self.set_pokemon(side, crit=crit)

    def set_field(self, **changes: Any) -> None:
        self.state = replace(self.state, field=replace(self.state.field, **changes))
        self._commit()

    def set_side_conditions(self, side: str, **changes: Any) -> None:
        current = self.state.field.left if side == "left" else self.state.field.right
        updated = replace(current, **changes)
        self.set_field(**{side: updated})

    def swap_sides(self) -> None:
        f = self.state.field
        self.state = CalcState(left=self.state.right, right=self.state.left, field=replace(f, left=f.right, right=f.left))
        self._commit()

    def reset(self) -> None:
        self.state = CalcState()
        self._commit()

    # -- internals ---------------------------------------------------------------------------

    def _commit(self) -> None:
        self._recompute(persist=True)

    def _recompute(self, *, persist: bool) -> None:
        key = self.state.key()
        cached = self._cache.get(key)
        if cached is None:
            cached = run(self.state, self.catalogs, self._calc)
            self._cache[key] = cached
            if len(self._cache) > 64:
                self._cache.popitem(last=False)
        else:
            self._cache.move_to_end(key)
        self.results = cached
        if persist and self._prefs is not None:
            try:
                self._prefs.set(PREF_STATE, self.state.to_dict())
            except Exception:  # noqa: BLE001 - persistence is a convenience
                pass
        self._notify(("state",))
        self._notify(("results",))


__all__ = ["CalcStore", "PREF_STATE", "engine_field", "engine_pokemon", "run", "run_side"]
