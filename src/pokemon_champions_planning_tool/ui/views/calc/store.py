"""Calculator store: state, mutations, results, the opponent sweep and persistence. Flet-free.

Every mutation recomputes both directions (eight engine calls, a few milliseconds), keeps the
result in a small cache keyed by the state, persists the state in the preferences and
notifies ``("state",)`` then ``("results",)``. The sweep (every species versus the attacker)
is computed on demand and notified as ``("sweep",)``.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from typing import Any

from sqlmodel import Session

from ....domain.damage import CalcPokemon, Field, Side
from ....domain.damage.ko import DescError
from ....domain.damage.util import get_final_speed
from ....domain.damage.state import FieldState as EngineFieldState, Mon
from ....domain.entities.box_entry import BoxEntry
from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.species import SpeciesInfo
from ....domain.stat_calc import MAX_POINTS_PER_STAT, MAX_POINTS_TOTAL, champions_stats, default_points_for_nature, points_total
from ....domain.type_chart import defensive_multiplier
from ....infrastructure.database.database import get_session
from ....infrastructure.database.repositories import BoxRepository
from ....infrastructure.database.repositories import TournamentRepository
from ....services.damage_calc_service import build_calc_move, calculate, pokemon_from_species
from ....services.tournament_service import TournamentBuild, TournamentService
from ...catalogs import Catalogs
from ...move_options import EMPTY_MOVE_OPTIONS, MoveOptions, invalidate_move_usage, move_options_for
from .state import (
    BOOST_STATS,
    DOUBLES_ONLY,
    CalcRequest,
    CalcResults,
    CalcState,
    FieldState,
    MoveResult,
    PokemonState,
    SideConditions,
    SweepEntry,
    TeamRating,
    classify,
    hits_to_ko,
    pokemon_from_slot,
    pokemon_from_species_id,
)

SessionFactory = Callable[[], AbstractContextManager[Session]]
Listener = Callable[[tuple], None]

PREF_STATE = "calc.state"
PREF_PRESETS = "calc.sweep_presets"
PREF_SWEEP_SORT = "calc.sweep_sort"
PREF_SWEEP_REGULATION = "calc.sweep_regulation"
PREF_SECTIONS = "calc.sections"

# Status moves the "Activate" toggle knows: stat stages on the user, field or side conditions,
# or a status on the opponent. Values are applied on activation and reverted on deactivation.
SELF_BOOSTS: dict[str, dict[str, int]] = {
    "Swords Dance": {"attack": 2}, "Nasty Plot": {"special_attack": 2}, "Dragon Dance": {"attack": 1, "speed": 1}, "Calm Mind": {"special_attack": 1, "special_defense": 1},
    "Bulk Up": {"attack": 1, "defense": 1}, "Iron Defense": {"defense": 2}, "Agility": {"speed": 2}, "Quiver Dance": {"special_attack": 1, "special_defense": 1, "speed": 1},
    "Shell Smash": {"attack": 2, "special_attack": 2, "speed": 2, "defense": -1, "special_defense": -1}, "Curse": {"attack": 1, "defense": 1, "speed": -1}, "Coil": {"attack": 1, "defense": 1},
    "Work Up": {"attack": 1, "special_attack": 1}, "Growth": {"attack": 1, "special_attack": 1}, "Howl": {"attack": 1}, "Amnesia": {"special_defense": 2}, "Cotton Guard": {"defense": 3},
    "Belly Drum": {"attack": 6}, "Victory Dance": {"attack": 1, "defense": 1, "speed": 1}, "Tidy Up": {"attack": 1, "speed": 1}, "Hone Claws": {"attack": 1}, "Rock Polish": {"speed": 2},
    "Autotomize": {"speed": 2}, "Acid Armor": {"defense": 2}, "Barrier": {"defense": 2}, "Defend Order": {"defense": 1, "special_defense": 1}, "Meditate": {"attack": 1},
    "Sharpen": {"attack": 1}, "Harden": {"defense": 1}, "Withdraw": {"defense": 1}, "Tail Glow": {"special_attack": 3}, "Geomancy": {"special_attack": 2, "special_defense": 2, "speed": 2},
    "Clangorous Soul": {"attack": 1, "defense": 1, "special_attack": 1, "special_defense": 1, "speed": 1}, "No Retreat": {"attack": 1, "defense": 1, "special_attack": 1, "special_defense": 1, "speed": 1},
    "Charge": {"special_defense": 1},
}
OWN_SIDE: dict[str, dict[str, Any]] = {"Reflect": {"reflect": True}, "Light Screen": {"light_screen": True}, "Aurora Veil": {"aurora_veil": True}, "Tailwind": {"tailwind": True},
                                       "Helping Hand": {"helping_hand": True}, "Protect": {"protect": True}, "Detect": {"protect": True}, "Charge": {"charge": True}, "Power Trick": {"power_trick": True}}
FOE_SIDE: dict[str, dict[str, Any]] = {"Stealth Rock": {"stealth_rock": True}, "Spikes": {"spikes": 1}, "Leech Seed": {"leech_seed": True}}
FIELD_EFFECTS: dict[str, dict[str, Any]] = {"Sunny Day": {"weather": "Sun"}, "Rain Dance": {"weather": "Rain"}, "Sandstorm": {"weather": "Sand"}, "Snowscape": {"weather": "Snow"},
                                            "Chilly Reception": {"weather": "Snow"}, "Electric Terrain": {"terrain": "Electric"}, "Grassy Terrain": {"terrain": "Grassy"},
                                            "Psychic Terrain": {"terrain": "Psychic"}, "Misty Terrain": {"terrain": "Misty"}, "Gravity": {"gravity": True},
                                            "Trick Room": {"trick_room": True}, "Magic Room": {"magic_room": True}, "Wonder Room": {"wonder_room": True}}
ABILITY_FIELD_EFFECTS: dict[str, dict[str, Any]] = {
    "Drought": {"weather": "Sun"},
    "Orichalcum Pulse": {"weather": "Sun"},
    "Drizzle": {"weather": "Rain"},
    "Primordial Sea": {"weather": "Rain"},
    "Sand Stream": {"weather": "Sand"},
    "Snow Warning": {"weather": "Snow"},
    "Electric Surge": {"terrain": "Electric"},
    "Hadron Engine": {"terrain": "Electric"},
    "Grassy Surge": {"terrain": "Grassy"},
    "Psychic Surge": {"terrain": "Psychic"},
    "Misty Surge": {"terrain": "Misty"},
}
FOE_STATUS: dict[str, str] = {"Will-O-Wisp": "brn", "Toxic": "tox", "Thunder Wave": "par", "Glare": "par", "Stun Spore": "par", "Nuzzle": "par", "Spore": "slp", "Sleep Powder": "slp",
                              "Hypnosis": "slp", "Dark Void": "slp", "Yawn": "slp", "Poison Powder": "psn", "Toxic Thread": "psn"}


def move_effect(name: str | None) -> str | None:
    """A short description of what activating this status move does, or None when unknown."""
    if not name:
        return None
    if name in SELF_BOOSTS:
        abbrev = {"attack": "Atk", "defense": "Def", "special_attack": "SpA", "special_defense": "SpD", "speed": "Spe"}
        return " ".join(f"{v:+d} {abbrev[k]}" for k, v in SELF_BOOSTS[name].items())
    if name in OWN_SIDE:
        return f"{name} on your side"
    if name in FOE_SIDE:
        return f"{name} on their side"
    if name in FIELD_EFFECTS:
        return "Sets " + ", ".join(f"{k.replace('_', ' ')} {v}" if not isinstance(v, bool) else k.replace("_", " ") for k, v in FIELD_EFFECTS[name].items())
    if name in FOE_STATUS:
        return f"Inflicts {dict(_STATUS_LABELS)[FOE_STATUS[name]].lower()}"
    return None


_STATUS_LABELS = (("brn", "Burn"), ("psn", "Poison"), ("tox", "Bad poison"), ("par", "Paralysis"), ("slp", "Sleep"), ("frz", "Freeze"))


def _engine_side(c: SideConditions) -> Side:
    return Side(spikes=c.spikes, is_sr=c.stealth_rock, is_reflect=c.reflect, is_light_screen=c.light_screen, is_protected=c.protect, is_seeded=c.leech_seed,
                is_charge=c.charge, is_tailwind=c.tailwind, is_helping_hand=c.helping_hand, is_power_trick=c.power_trick, is_friend_guard=c.friend_guard, is_aurora_veil=c.aurora_veil)


def engine_field(f: FieldState, *, attacker_is_left: bool) -> Field:
    a, d = (f.left, f.right) if attacker_is_left else (f.right, f.left)
    return Field(game_type="Doubles" if f.game_type == "doubles" else "Singles", weather=None if f.weather == "none" else f.weather,
                 terrain=None if f.terrain == "none" else f.terrain, is_gravity=f.gravity, is_magic_room=f.magic_room, is_wonder_room=f.wonder_room,
                 attacker_side=_engine_side(a), defender_side=_engine_side(d))


def engine_pokemon(p: PokemonState, species: SpeciesInfo) -> CalcPokemon:
    max_hp = champions_stats(species.stats, p.points, p.nature if p.nature != "hardy" else None).hp
    cur = max(1, min(max_hp, round(max_hp * p.hp_pct / 100)))
    return pokemon_from_species(species, ability=p.ability, ability_on=p.ability_on, item=p.item, nature=p.nature, points=p.points, boosts=p.boosts,
                                cur_hp=cur, status="" if p.status == "none" else p.status, allies_fainted=p.allies_fainted)


def final_speed(p: PokemonState, species: SpeciesInfo, field: FieldState, side: str) -> int:
    """Speed the game would use for turn order under the field (Tailwind, paralysis, Scarf…)."""
    mon = Mon.from_input(engine_pokemon(p, species))
    ef = engine_field(field, attacker_is_left=(side == "left"))
    return get_final_speed(mon, EngineFieldState.from_input(ef), EngineFieldState.from_input(ef).attacker_side)


def run_side(attacker: PokemonState, defender: PokemonState, field: Field, catalogs: Catalogs, calc: Callable = calculate,
             a_species: SpeciesInfo | None = None, d_species: SpeciesInfo | None = None,
             *, fast: bool = False, a_engine: CalcPokemon | None = None, d_engine: CalcPokemon | None = None,
             prebuilt_moves: list[tuple[Any, str]] | None = None) -> tuple[MoveResult, ...]:
    a_species = a_species or catalogs.species_for(attacker.species)
    d_species = d_species or catalogs.species_for(defender.species)
    if a_species is None or d_species is None:
        return ()
    a = a_engine if a_engine is not None else engine_pokemon(attacker, a_species)
    d = d_engine if d_engine is not None else engine_pokemon(defender, d_species)
    out: list[MoveResult] = []
    moves_iter = prebuilt_moves if prebuilt_moves is not None else [
        (build_calc_move(name, catalogs, attacker_ability=a.ability or (a.abilities[0] if a.abilities else None), is_crit=bool(attacker.crit[index])) if name else None, name)
        for index, name in enumerate(attacker.moves)
    ]
    for index, (move, name) in enumerate(moves_iter):
        if not name:
            continue
        if move is None:
            out.append(MoveResult(index, name, None, None, 0, 0, 0.0, 0.0, (), "", "", error="Not in the move catalogue"))
            continue
        if move.category == "Status":
            out.append(MoveResult(index, name, move.type, move.category, 0, 0, 0.0, 0.0, (), "", "", error="Status move"))
            continue
        try:
            result = calc(a, d, move, field)
            eff = defensive_multiplier(result.move.type.lower(), [t.lower() for t in result.defender.types]) if result.move.type != "???" else 1.0
            lo, hi = result.range()
            if hi == 0:
                out.append(MoveResult(index, name, result.move.type, move.category, 0, 0, 0.0, 0.0, (), "", "", error="No effect", bp=result.move_bp, effectiveness=eff))
                continue
            if fast:
                # The sweep shows a percentage range and a threat class, nothing else.
                # ``desc()`` computes the KO chance internally, so building it here undid
                # the saving of skipping ``ko_chance()`` below — it was about half the sweep.
                description = ""
                ko_text = ""
                recoil = None
                recovery = None
            else:
                try:
                    description = result.desc()
                except DescError:
                    description = ""
                try:
                    ko_text = result.ko_chance().text
                except DescError:
                    ko_text = ""
                recoil = result.recoil()[1] or None
                recovery = result.recovery()[1] or None
            mr = MoveResult(index, name, result.move.type, move.category, lo, hi, result.min_pct, result.max_pct, tuple(result.rolls), description, ko_text,
                            recoil, recovery, bp=result.move_bp, effectiveness=eff)
            out.append(replace(mr, ko_hits=hits_to_ko(mr)))
        except Exception as exc:  # noqa: BLE001 - one bad move must not hide the others
            out.append(MoveResult(index, name, move.type, move.category, 0, 0, 0.0, 0.0, (), "", "", error=f"{type(exc).__name__}: {exc}"))
    return tuple(out)


def run(state: CalcState, catalogs: Catalogs, calc: Callable = calculate) -> CalcResults:
    left = catalogs.species_for(state.left.species)
    right = catalogs.species_for(state.right.species)
    return CalcResults(
        left_vs_right=run_side(state.left, state.right, engine_field(state.field, attacker_is_left=True), catalogs, calc, left, right),
        right_vs_left=run_side(state.right, state.left, engine_field(state.field, attacker_is_left=False), catalogs, calc, right, left),
        left_name=left.name if left else "", right_name=right.name if right else "",
        left_speed=final_speed(state.left, left, state.field, "left") if left else 0,
        right_speed=final_speed(state.right, right, state.field, "right") if right else 0,
    )


def best_of(results: tuple[MoveResult, ...]) -> MoveResult | None:
    ok = [r for r in results if r.ok and r.max_pct > 0]
    return max(ok, key=lambda r: (r.min_pct + r.max_pct)) if ok else None


class CalcStore:
    def __init__(self, catalogs: Catalogs | None = None, session_factory: SessionFactory | None = get_session, *, prefs: Any = None,
                 calculate_fn: Callable | None = None, team_store: Any = None) -> None:
        self.catalogs = catalogs or Catalogs()
        self._sf = session_factory
        self._prefs = prefs
        self._calc = calculate_fn or calculate
        self.team_store = team_store
        self.state = CalcState()
        self.results = CalcResults()
        self.sweep: tuple[SweepEntry, ...] = ()
        self.sweep_presets = True
        self.sweep_sort: str = "usage"
        self.sweep_regulation: str = "latest"
        self._usage_cache: dict[tuple[str, str], dict[str, int]] = {}
        self._sweep_key: str | None = None
        self._preset_moves: dict[str, list[str]] | None = None
        self._preset_builds: dict[str, TournamentBuild] | None = None
        self._cache: OrderedDict[str, CalcResults] = OrderedDict()
        self._listeners: list[Listener] = []
        self.loaded = False
        # Saving the state writes preferences.json. The view sets this to a debounced call to
        # ``save_state`` so a burst of edits (a slider drag) writes once; without it (tests,
        # scripts) every commit saves at once.
        self.defer_save: Callable[[], None] | None = None
        self._unsaved = False
        # Team ratings (your team members against the rival in the Defender panel).
        self._team_version = 0
        self._team_members: dict[str, tuple[int, PokemonState | None]] = {}
        self._ratings_cache: tuple[str, dict[str, TeamRating]] | None = None

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
                self.sweep_presets = bool(self._prefs.get(PREF_PRESETS, True))
                self.sweep_sort = str(self._prefs.get(PREF_SWEEP_SORT, "usage"))
                self.sweep_regulation = str(self._prefs.get(PREF_SWEEP_REGULATION, "latest"))
            except Exception:  # noqa: BLE001 - a corrupt preference must not break the view
                self.state = CalcState()
        self._recompute(persist=False)

    def _apply_ability_field(self, ability: str | None, *, force: bool = False) -> None:
        if not ability:
            return
        effect = ABILITY_FIELD_EFFECTS.get(ability)
        if effect:
            field_updates = {}
            for k, v in effect.items():
                cur = getattr(self.state.field, k, "none")
                if force or cur in ("none", None, ""):
                    field_updates[k] = v
            if field_updates:
                self.state = replace(self.state, field=replace(self.state.field, **field_updates))

    def apply_request(self, req: CalcRequest) -> None:
        if req.attacker is not None:
            self.state = self.state.with_side("left", req.attacker)
            self._apply_ability_field(req.attacker.ability)
        if req.defender is not None:
            self.state = self.state.with_side("right", req.defender)
            self._apply_ability_field(req.defender.ability)
        self._commit()

    def load_species(self, side: str, canonical_id: str, *, preset: bool = False, source: str | None = None) -> None:
        if preset:
            p, _found = self.preset_pokemon(canonical_id, source=source)
        else:
            species = self.catalogs.species_for(canonical_id)
            p = pokemon_from_species_id(species.canonical_id if species else canonical_id, species, source=source or "")
        self.state = self.state.with_side(side, p)
        self._apply_ability_field(p.ability)
        self._commit()

    def preset_pokemon(self, canonical_id: str, *, source: str | None = None) -> tuple[PokemonState, bool]:
        """The species with its most-used tournament set; True when tournament data had one.

        Without a build it falls back to the species' preset moves (or none) on a plain set.
        Shared by the Defender panel and rival teams entered at team preview.
        """
        species = self.catalogs.species_for(canonical_id)
        cid = species.canonical_id if species else canonical_id
        base_cid = species.base_species_id if species else cid
        build = self.preset_builds().get(cid) or self.preset_builds().get(base_cid)
        if build is not None:
            nature = (build.nature or "hardy").lower()
            points = default_points_for_nature(nature, species.stats if species else None)
            four_moves = list(build.moves)[:4]
            four_moves += [None] * (4 - len(four_moves))
            item = build.item
            if species and species.is_mega and species.required_item and not item:
                item = species.required_item
            if species and species.is_mega and species.abilities:
                ability = species.abilities[0]
            else:
                ability = build.ability or (species.abilities[0] if species and species.abilities else None)
            if source:
                src = f"{source} · {nature.title()}" if build.nature else source
            else:
                src = f"Tournament preset · {nature.title()}" if build.nature else "Tournament preset"
            return PokemonState(
                species=cid,
                nature=nature,
                points=points,
                ability=ability,
                item=item,
                moves=four_moves,
                source=src,
            ), True
        moves = self.preset_moves().get(cid, self.preset_moves().get(base_cid, []))
        return pokemon_from_species_id(cid, species, source=source or "", moves=moves), False

    def load_pokemon(self, side: str, pokemon: PokemonState) -> None:
        self.state = self.state.with_side(side, pokemon)
        self._apply_ability_field(pokemon.ability)
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

    def speed(self, side: str) -> int:
        return self.results.left_speed if side == "left" else self.results.right_speed

    def speed_order(self) -> str:
        """"left", "right" or "tie": who moves first under the field (Trick Room reverses)."""
        a, b = self.results.left_speed, self.results.right_speed
        if a == b:
            return "tie"
        first = "left" if a > b else "right"
        if self.state.field.trick_room:
            first = "right" if first == "left" else "left"
        return first

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
        matches = self.catalogs.search_species(query, limit=24)
        umap = self.get_usage_map()
        if not umap:
            return matches[:8]
        q = query.strip().lower()

        def rank_key(s: SpeciesInfo) -> tuple[int, int, int, str]:
            cid = s.canonical_id.lower()
            base_cid = (s.base_species_id or "").lower()
            usage = umap.get(cid) or umap.get(base_cid, 0)
            exact = 0 if s.name.lower() == q or cid == q else 1
            starts = 0 if s.name.lower().startswith(q) else 1
            return (exact, starts, -usage, s.name.lower())

        return sorted(matches, key=rank_key)[:8]

    def damage_preview(self, side: str, move_name: str | None) -> MoveResult | None:
        """What ``move_name`` used by ``side`` would do to the other Pokémon under the current
        field (for the move picker); None when either side has no species."""
        if not move_name:
            return None
        other = "right" if side == "left" else "left"
        a_species = self.species(side)
        d_species = self.species(other)
        if a_species is None or d_species is None:
            return None
        attacker = replace(self.state.side(side), moves=[move_name, None, None, None], crit=[False, False, False, False])
        field = engine_field(self.state.field, attacker_is_left=(side == "left"))
        results = run_side(attacker, self.state.side(other), field, self.catalogs, self._calc, a_species, d_species)
        return results[0] if results else None

    def fill_top_moves(self, side: str, *, candidates: int = 24) -> int:
        """Fill the empty move slots with likely picks; returns how many were filled.

        Tournament usage for the species decides when there is any. Otherwise the damaging
        moves are ranked by what they do to the other side (by power when there is no other
        side yet); only the ``candidates`` strongest by power are run through the engine.
        """
        p = self.state.side(side)
        empty = [i for i, name in enumerate(p.moves) if not name]
        if not empty or self.species(side) is None:
            return 0
        options = self.move_options(side)
        taken = {name.lower() for name in p.moves if name}
        pool = [m for m in options.legal if m.is_legal and m.name.lower() not in taken]
        used = sorted((m for m in pool if options.usage.get(m.move_id, 0) > 0), key=lambda m: -options.usage[m.move_id])
        if used:
            picks = [m.name for m in used]
        else:
            damaging = sorted((m for m in pool if (m.category or "").lower() != "status" and m.power),
                              key=lambda m: -(m.power or 0) * (m.accuracy or 100))[:candidates]

            def score(m) -> float:
                result = self.damage_preview(side, m.name)
                return result.max_pct if result is not None and result.ok else (m.power or 0) / 1000
            picks = [m.name for m in sorted(damaging, key=score, reverse=True)]
        moves = list(p.moves)
        filled = 0
        for index, name in zip(empty, picks):
            moves[index] = name
            filled += 1
        if filled:
            self.set_pokemon(side, moves=moves)
        return filled

    def section_open(self, name: str, default: bool = True) -> bool:
        sections = self._prefs.get(PREF_SECTIONS, {}) if self._prefs is not None else {}
        return bool(sections.get(name, default)) if isinstance(sections, dict) else default

    def set_section_open(self, name: str, value: bool) -> None:
        if self._prefs is None:
            return
        sections = self._prefs.get(PREF_SECTIONS, {})
        sections = dict(sections) if isinstance(sections, dict) else {}
        sections[name] = bool(value)
        try:
            self._prefs.set(PREF_SECTIONS, sections)
        except Exception:  # noqa: BLE001 - a layout preference is a convenience
            pass

    def points_left(self, side: str) -> int:
        return MAX_POINTS_TOTAL - points_total(self.state.side(side).points)

    def team_slots(self) -> list[Any]:
        """Filled slots of the active team (via the shared team store), or []."""
        if self.team_store is None:
            return []
        try:
            if not getattr(self.team_store, "teams", None) and self.team_store.active_team_id is None:
                self.team_store.load()
        except Exception:  # noqa: BLE001 - the rail is a convenience
            return []
        return [s for s in self.team_store.slots if s.filled]

    def box_entries(self) -> list[BoxEntry]:
        if self._sf is None:
            return []
        try:
            with self._sf() as s:
                return BoxRepository(s).list_entries(include_planned=False)
        except Exception:  # noqa: BLE001
            return []

    def preset_builds(self) -> dict[str, TournamentBuild]:
        """Top build (nature, item, ability, top-4 roster moves) per species from tournament data."""
        if self._preset_builds is None:
            self._preset_builds = {}
            if self._sf is not None:
                try:
                    with self._sf() as s:
                        pref = TournamentRepository(s).get_state("pref_battle_format") or "doubles"
                        self._preset_builds = TournamentService(s).common_builds_by_species(top_moves=4, battle_format=pref)
                except Exception:  # noqa: BLE001 - presets are a convenience
                    self._preset_builds = {}
        return self._preset_builds

    @property
    def presets_ready(self) -> bool:
        """True when ``preset_builds`` would answer without aggregating the roster table."""
        return self._preset_builds is not None

    def preset_moves(self) -> dict[str, list[str]]:
        """Top-4 roster moves per species from the tournament data (cached for the session)."""
        builds = self.preset_builds()
        if builds:
            return {cid: list(b.moves) for cid, b in builds.items()}
        if self._preset_moves is None:
            self._preset_moves = {}
            if self._sf is not None:
                try:
                    with self._sf() as s:
                        pref = TournamentRepository(s).get_state("pref_battle_format") or "doubles"
                        self._preset_moves = TournamentService(s).common_moves_by_species(top=4, battle_format=pref)
                except Exception:  # noqa: BLE001 - presets are a convenience
                    self._preset_moves = {}
        return self._preset_moves

    def latest_regulation(self) -> str:
        if self._sf is not None:
            try:
                with self._sf() as s:
                    return TournamentRepository(s).get_latest_regulation()
            except Exception:
                pass
        return "Regulation M-C"

    def available_regulations(self) -> list[str]:
        if self._sf is not None:
            try:
                with self._sf() as s:
                    return TournamentRepository(s).list_regulations_by_date()
            except Exception:
                pass
        return ["Regulation M-C", "Regulation M-B", "Regulation M-A"]

    def get_usage_map(self, regulation: str | None = None) -> dict[str, int]:
        """Cached {canonical_id: team_count} for the specified regulation (defaults to active sweep_regulation)."""
        if self._sf is None:
            return {}
        try:
            with self._sf() as s:
                repo = TournamentRepository(s)
                bformat = repo.get_state("pref_battle_format") or "doubles"
                target_reg = self.sweep_regulation if regulation is None else regulation
                reg = repo.get_latest_regulation() if target_reg == "latest" else target_reg
                cache_key = (reg, bformat)
                if cache_key in self._usage_cache:
                    return self._usage_cache[cache_key]
                umap = repo.species_usage_by_regulation(regulation=reg, battle_format=bformat)
                self._usage_cache[cache_key] = umap
                return umap
        except Exception:
            return {}

    def invalidate_usage_cache(self) -> None:
        """Clear cached tournament usage data so it reloads on next lookup."""
        self._usage_cache.clear()
        self._sweep_key = None

    def refresh_catalogs(self, catalogs: Catalogs) -> None:
        """Swap in a reloaded catalogue and recompute against it.

        A first launch opens before the Showdown data has arrived, so the species, moves
        and items the calculator needs can land while the view is already on screen.
        """
        self.catalogs = catalogs
        self._cache.clear()
        self._sweep_key = None
        self.invalidate_presets()
        self.invalidate_team_ratings()
        self._recompute(persist=False)

    def invalidate_presets(self) -> None:
        """Clear cached tournament builds and moves so they reload on next lookup."""
        self._preset_builds = None
        self._preset_moves = None
        self.invalidate_usage_cache()
        invalidate_move_usage()

    # -- mutations ---------------------------------------------------------------------------

    def set_pokemon(self, side: str, **changes: Any) -> None:
        self.state = self.state.with_side(side, replace(self.state.side(side), **changes))
        if "ability" in changes:
            self._apply_ability_field(changes["ability"], force=True)
        self._commit()

    def switch_form(self, side: str, form_canonical_id: str) -> None:
        """Switch a Pokémon between its base form and Mega Evolution in-place.

        Preserves the Pokémon's points spread, nature, moves, stat stage boosts,
        HP percentage, status, and source, while updating the species base stats,
        typing, ability, and required Mega Stone.
        """
        p = self.state.side(side)
        if not p.species or p.species == form_canonical_id:
            return
        target_species = self.catalogs.species_for(form_canonical_id)
        if target_species is None:
            return

        changes: dict[str, Any] = {"species": target_species.canonical_id}
        if target_species.is_mega:
            if target_species.abilities:
                changes["ability"] = target_species.abilities[0]
            if target_species.required_item and p.item != target_species.required_item:
                changes["item"] = target_species.required_item
        else:
            base_species = self.catalogs.species_for(target_species.base_species_id) or target_species
            current_species = self.catalogs.species_for(p.species)
            if current_species and current_species.is_mega and base_species.abilities:
                if p.ability not in base_species.abilities:
                    changes["ability"] = base_species.abilities[0]

        self.set_pokemon(side, **changes)

    def set_item(self, side: str, item_name: str | None) -> None:
        """Set the held item on a Pokémon, automatically synchronizing Mega Evolution form."""
        p = self.state.side(side)
        clean_item = (item_name or "").strip() or None
        if not p.species:
            self.set_pokemon(side, item=clean_item)
            return

        mega_cid = self.catalogs.mega_for_item(p.species, clean_item)
        if mega_cid and mega_cid != p.species:
            self.switch_form(side, mega_cid)
            self.set_pokemon(side, item=clean_item)
            return

        current_species = self.catalogs.species_for(p.species)
        if current_species and current_species.is_mega:
            if not clean_item or clean_item.strip().lower() != (current_species.required_item or "").strip().lower():
                base_cid = current_species.base_species_id
                self.switch_form(side, base_cid)
                self.set_pokemon(side, item=clean_item)
                return

        self.set_pokemon(side, item=clean_item)

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

    def bump_boost(self, side: str, stat: str, delta: int) -> None:
        self.set_boost(side, stat, self.state.side(side).boosts.get(stat, 0) + delta)

    def set_hp_pct(self, side: str, pct: float) -> None:
        self.set_pokemon(side, hp_pct=max(0.0, min(100.0, float(pct))))

    def set_hp_abs(self, side: str, hp: int) -> None:
        max_hp = self.max_hp(side)
        if max_hp:
            self.set_hp_pct(side, 100.0 * max(1, min(max_hp, int(hp))) / max_hp)

    def set_move(self, side: str, index: int, name: str | None) -> None:
        p = self.state.side(side)
        if p.active[index]:
            self.toggle_move_effect(side, index)
            p = self.state.side(side)
        moves = list(p.moves)
        moves[index] = (name or "").strip() or None
        self.set_pokemon(side, moves=moves)

    def toggle_crit(self, side: str, index: int) -> None:
        crit = list(self.state.side(side).crit)
        crit[index] = not crit[index]
        self.set_pokemon(side, crit=crit)

    def toggle_move_effect(self, side: str, index: int) -> bool:
        """Apply (or revert) a status move's known effect. Returns True when the move has one."""
        p = self.state.side(side)
        name = p.moves[index]
        if not name or move_effect(name) is None:
            return False
        turning_on = not p.active[index]
        sign = 1 if turning_on else -1
        other = "right" if side == "left" else "left"
        active = list(p.active)
        active[index] = turning_on
        if name in SELF_BOOSTS:
            boosts = dict(p.boosts)
            for stat, delta in SELF_BOOSTS[name].items():
                value = max(-6, min(6, boosts.get(stat, 0) + sign * delta))
                if value:
                    boosts[stat] = value
                else:
                    boosts.pop(stat, None)
            self.state = self.state.with_side(side, replace(p, boosts=boosts, active=active))
        elif name in OWN_SIDE or name in FOE_SIDE:
            target = side if name in OWN_SIDE else other
            effect = OWN_SIDE.get(name) or FOE_SIDE[name]
            current = self.state.field.left if target == "left" else self.state.field.right
            changes = {k: (v if turning_on else (0 if isinstance(v, int) and not isinstance(v, bool) else False)) for k, v in effect.items()}
            self.state = replace(self.state.with_side(side, replace(p, active=active)), field=replace(self.state.field, **{target: replace(current, **changes)}))
        elif name in FIELD_EFFECTS:
            effect = FIELD_EFFECTS[name]
            changes = {k: (v if turning_on else ("none" if isinstance(v, str) else False)) for k, v in effect.items()}
            self.state = replace(self.state.with_side(side, replace(p, active=active)), field=replace(self.state.field, **changes))
        elif name in FOE_STATUS:
            foe = self.state.side(other)
            self.state = self.state.with_side(side, replace(p, active=active)).with_side(other, replace(foe, status=FOE_STATUS[name] if turning_on else "none"))
        self._commit()
        return True

    def set_field(self, **changes: Any) -> None:
        field = replace(self.state.field, **changes)
        if field.game_type == "singles":
            # Doubles-only conditions are hidden in Singles; drop them so they can't
            # still change the damage while invisible.
            off = {key: False for key in DOUBLES_ONLY}
            field = replace(field, left=replace(field.left, **off), right=replace(field.right, **off))
        self.state = replace(self.state, field=field)
        self._commit()

    def toggle_field(self, key: str, value: Any = True) -> None:
        """Tiles: a bool flips; weather/terrain set to ``value`` or clear when already set."""
        current = getattr(self.state.field, key)
        if isinstance(current, bool):
            self.set_field(**{key: not current})
        else:
            self.set_field(**{key: "none" if current == value else value})

    def set_side_conditions(self, side: str, **changes: Any) -> None:
        current = self.state.field.left if side == "left" else self.state.field.right
        updated = replace(current, **changes)
        self.set_field(**{side: updated})

    def toggle_side(self, side: str, key: str) -> None:
        current = self.state.field.left if side == "left" else self.state.field.right
        value = getattr(current, key)
        self.set_side_conditions(side, **{key: (0 if value else 1) if key == "spikes" else not value})

    def swap_sides(self) -> None:
        f = self.state.field
        self.state = CalcState(left=self.state.right, right=self.state.left, field=replace(f, left=f.right, right=f.left))
        self._commit()

    def reset(self) -> CalcState:
        """Clear both Pokémon and the field; returns the previous state for Undo."""
        previous = self.state
        self.state = CalcState()
        self._commit()
        return previous

    def clear_conditions(self) -> CalcState:
        """Reset the field and every stat modifier; keep both Pokémon as they are.

        Clears weather, terrain, rooms, speed control and side conditions (the format
        stays), and on both sides: stat stages, status, activated abilities and the
        applied status-move effects. Species, moves, spreads, items and HP are kept.
        Returns the previous state for Undo.
        """
        previous = self.state
        cleared = {side: replace(self.state.side(side), boosts={}, status="none", ability_on=False, active=[False, False, False, False])
                   for side in ("left", "right")}
        self.state = CalcState(left=cleared["left"], right=cleared["right"], field=FieldState(game_type=self.state.field.game_type))
        self._commit()
        return previous

    def has_conditions(self) -> bool:
        """True when ``clear_conditions`` would change anything."""
        if self.state.field != FieldState(game_type=self.state.field.game_type):
            return True
        return any(p.boosts or p.status != "none" or p.ability_on or any(p.active) for p in (self.state.left, self.state.right))

    def restore(self, state: CalcState) -> None:
        """Put back a state returned by ``reset`` (or ``clear_conditions``)."""
        self.state = state
        self._commit()

    def set_sweep_presets(self, value: bool) -> None:
        self.sweep_presets = bool(value)
        if self._prefs is not None:
            try:
                self._prefs.set(PREF_PRESETS, self.sweep_presets)
            except Exception:  # noqa: BLE001
                pass
        self._sweep_key = None
        self._notify(("sweep",))

    # -- opponent sweep ----------------------------------------------------------------------

    # PokemonState fields the sweep never reads: where the attacker came from, the notes on
    # its assumptions, and which status-move effects are applied (their result is already in
    # the boosts and the field). Changing only these must not re-run every opponent.
    _SWEEP_IGNORES = ("source", "assumptions", "active")

    def sweep_key(self) -> str:
        d = self.state.to_dict()
        left = {k: v for k, v in d["left"].items() if k not in self._SWEEP_IGNORES}
        return "|".join((str(left), str(d["field"]), str(self.sweep_presets), str(self.sweep_regulation)))

    def sweep_stale(self) -> bool:
        return self._sweep_key != self.sweep_key()

    def _order_sweep(self, entries: list[SweepEntry] | tuple[SweepEntry, ...], sort_key: str) -> tuple[SweepEntry, ...]:
        res = list(entries)
        if sort_key == "usage":
            res.sort(key=lambda e: e.name.lower())
            res.sort(key=lambda e: e.usage_count, reverse=True)
        elif sort_key == "name":
            res.sort(key=lambda e: e.name.lower())
        elif sort_key == "speed":
            res.sort(key=lambda e: e.name.lower())
            res.sort(key=lambda e: e.speed, reverse=True)
        elif sort_key == "threat":
            threat_ranks = {"threat": 0, "wall": 1, "neutral": 2, "mitigated": 3, "crushed": 4}
            res.sort(key=lambda e: e.name.lower())
            res.sort(key=lambda e: e.usage_count, reverse=True)
            res.sort(key=lambda e: threat_ranks.get(e.klass, 99))
        else:
            res.sort(key=lambda e: e.name.lower())
        return tuple(res)

    def publish_progressive_sweep(self, entries: tuple[SweepEntry, ...]) -> None:
        """Publish partial progressive sweep results without marking the full sweep as complete."""
        self.sweep = self._order_sweep(entries, self.sweep_sort)
        self._notify(("sweep",))

    def compute_sweep(self, on_progressive: Callable[[tuple[SweepEntry, ...]], None] | None = None) -> tuple[SweepEntry, ...]:
        """Every legal species against the attacker: their class, speed and both best moves.
        Pure computation (no notification) so it can run on a worker thread; call
        ``publish_sweep`` with the result on the UI thread."""
        key = self.sweep_key()
        attacker = self.state.left
        a_species = self.catalogs.species_for(attacker.species)
        if a_species is None or not any(attacker.moves):
            return ()
        builds = self.preset_builds() if self.sweep_presets else {}
        field_ab = engine_field(self.state.field, attacker_is_left=True)
        field_ba = engine_field(self.state.field, attacker_is_left=False)
        my_speed = final_speed(attacker, a_species, self.state.field, "left")
        umap = self.get_usage_map(self.sweep_regulation)

        a_engine = engine_pokemon(attacker, a_species)
        a_moves = [
            (
                build_calc_move(
                    name,
                    self.catalogs,
                    attacker_ability=a_engine.ability or (a_engine.abilities[0] if a_engine.abilities else None),
                    is_crit=bool(attacker.crit[i]),
                ),
                name,
            )
            if name
            else (None, None)
            for i, name in enumerate(attacker.moves)
        ]

        legal_species = [s for s in self.catalogs.species_by_canonical.values() if s.is_legal]
        legal_species.sort(
            key=lambda s: (
                umap.get(s.canonical_id.lower()) or umap.get((s.base_species_id or "").lower(), 0),
                s.name.lower(),
            ),
            reverse=True,
        )

        entries: list[SweepEntry] = []
        notified_progressive = False
        for species in legal_species:
            build = (builds.get(species.canonical_id) or builds.get(species.base_species_id)) if builds else None
            if build is not None:
                their_moves = list(build.moves)[:4]
                nature = (build.nature or "hardy").lower()
                points = default_points_for_nature(nature, species.stats)
                item = build.item or (species.required_item if species.is_mega else None)
                ability = species.abilities[0] if (species.is_mega and species.abilities) else (build.ability or (species.abilities[0] if species.abilities else None))
                four = list(their_moves) + [None] * (4 - len(their_moves))
                defender = PokemonState(
                    species=species.canonical_id,
                    nature=nature,
                    points=points,
                    ability=ability,
                    item=item,
                    moves=four,
                )
            else:
                their_moves = []
                defender = pokemon_from_species_id(species.canonical_id, species)
            d_engine = engine_pokemon(defender, species)
            yours = best_of(
                run_side(
                    attacker, defender, field_ab, self.catalogs, self._calc,
                    a_species, species,
                    fast=True, a_engine=a_engine, d_engine=d_engine, prebuilt_moves=a_moves,
                )
            )
            theirs = (
                best_of(
                    run_side(
                        defender, attacker, field_ba, self.catalogs, self._calc,
                        species, a_species,
                        fast=True, a_engine=d_engine, d_engine=a_engine,
                    )
                )
                if their_moves
                else None
            )
            speed = final_speed(defender, species, self.state.field, "right")
            faster = (my_speed > speed) != self.state.field.trick_room if my_speed != speed else False
            cid_lower = species.canonical_id.lower()
            base_lower = (species.base_species_id or "").lower()
            usage = umap.get(cid_lower) or umap.get(base_lower, 0)
            entries.append(SweepEntry(species.canonical_id, species.name, speed, classify(yours, theirs, faster), yours, theirs, faster, bool(their_moves), usage_count=usage))

            if on_progressive is not None and not notified_progressive and len(entries) >= 30:
                notified_progressive = True
                try:
                    on_progressive(self._order_sweep(entries, self.sweep_sort))
                except Exception:  # noqa: BLE001
                    pass

        self._sweep_key = key
        return self._order_sweep(entries, self.sweep_sort)

    def publish_sweep(self, entries: tuple[SweepEntry, ...]) -> None:
        self.sweep = self._order_sweep(entries, self.sweep_sort)
        self._sweep_key = self.sweep_key()
        self._notify(("sweep",))

    # -- team ratings ------------------------------------------------------------------------

    # The rival's fields that no rating reads (see ``_SWEEP_IGNORES``).
    _RATING_IGNORES = ("source", "assumptions", "active")

    def team_rating_key(self) -> str:
        """What the team ratings depend on: the rival as set up, the field and the team."""
        d = self.state.to_dict()
        rival = {k: v for k, v in d["right"].items() if k not in self._RATING_IGNORES}
        team_id = getattr(self.team_store, "active_team_id", None) if self.team_store is not None else None
        return "|".join((str(rival), str(d["field"]), str(team_id), str(self._team_version)))

    def invalidate_team_ratings(self) -> None:
        """The team (or the catalogue) changed: the next ``rate_team`` recomputes."""
        self._team_version += 1
        self._team_members.clear()

    def rate_team(self) -> dict[str, TeamRating]:
        """Each active team member against the rival in the Defender panel, keyed by slot.

        The opponents sweep turned around: the member is "you" (attacker, your side's
        conditions), the rival is the defender. At most six members, each two ``run_side``
        calls in fast mode. Pure computation, so it can run on a worker; the last result
        is kept per ``team_rating_key``.
        """
        key = self.team_rating_key()
        cached = self._ratings_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        ratings = self._rate_team()
        self._ratings_cache = (key, ratings)
        return ratings

    def _rate_team(self) -> dict[str, TeamRating]:
        rival = self.state.right
        r_species = self.catalogs.species_for(rival.species) if rival.species else None
        if r_species is None:
            return {}
        slots = self.team_slots()
        if not slots:
            return {}
        team_id = getattr(self.team_store, "active_team_id", None)
        field = self.state.field
        field_ab = engine_field(field, attacker_is_left=True)
        field_ba = engine_field(field, attacker_is_left=False)
        r_engine = engine_pokemon(rival, r_species)
        r_speed = final_speed(rival, r_species, field, "right")
        ratings: dict[str, TeamRating] = {}
        for slot in slots:
            slot_key = f"{team_id}:{slot.position}"
            member = self._member_state(slot_key, slot)
            m_species = self.catalogs.species_for(member.species) if member is not None else None
            if member is None or m_species is None:
                continue
            m_engine = engine_pokemon(member, m_species)
            yours = best_of(run_side(member, rival, field_ab, self.catalogs, self._calc, m_species, r_species,
                                     fast=True, a_engine=m_engine, d_engine=r_engine))
            theirs = best_of(run_side(rival, member, field_ba, self.catalogs, self._calc, r_species, m_species,
                                      fast=True, a_engine=r_engine, d_engine=m_engine))
            m_speed = final_speed(member, m_species, field, "left")
            faster = (m_speed > r_speed) != field.trick_room if m_speed != r_speed else False
            ratings[slot_key] = TeamRating(slot_key, m_species.name, classify(yours, theirs, faster), yours, theirs, m_speed, r_speed, faster)
        return ratings

    def _member_state(self, slot_key: str, slot: Any) -> PokemonState | None:
        """The member's calculator state, rebuilt only when its slot object changed."""
        marker = id(slot.member)
        cached = self._team_members.get(slot_key)
        if cached is not None and cached[0] == marker:
            return cached[1]
        state = pokemon_from_slot(slot, self.catalogs)
        self._team_members[slot_key] = (marker, state)
        return state

    def set_sweep_sort(self, sort_key: str, regulation: str | None = None) -> None:
        """Change the sort order or regulation for the opponent sweep and notify the UI immediately."""
        changed = False
        if sort_key != self.sweep_sort:
            self.sweep_sort = sort_key
            changed = True
            if self._prefs is not None:
                try:
                    self._prefs.set(PREF_SWEEP_SORT, self.sweep_sort)
                except Exception:
                    pass
        if regulation is not None and regulation != self.sweep_regulation:
            self.sweep_regulation = regulation
            changed = True
            self._sweep_key = None
            if self._prefs is not None:
                try:
                    self._prefs.set(PREF_SWEEP_REGULATION, self.sweep_regulation)
                except Exception:
                    pass
            umap = self.get_usage_map(self.sweep_regulation)
            updated_entries = []
            for e in self.sweep:
                cid_lower = e.canonical_id.lower()
                species = self.catalogs.species_for(e.canonical_id)
                base_lower = (species.base_species_id or "").lower() if species else cid_lower
                usage = umap.get(cid_lower) or umap.get(base_lower, 0)
                updated_entries.append(replace(e, usage_count=usage))
            self.sweep = self._order_sweep(updated_entries, self.sweep_sort)
            self._notify(("sweep",))
            return

        if changed or not self.sweep:
            self.sweep = self._order_sweep(self.sweep, self.sweep_sort)
            self._notify(("sweep",))

    # -- internals ---------------------------------------------------------------------------

    def save_state(self) -> None:
        """Write the calculation to the preferences if it changed since the last save."""
        if not self._unsaved or self._prefs is None:
            return
        self._unsaved = False
        try:
            self._prefs.set(PREF_STATE, self.state.to_dict())
        except Exception:  # noqa: BLE001 - persistence is a convenience
            pass

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
            self._unsaved = True
            if self.defer_save is not None:
                self.defer_save()
            else:
                self.save_state()
        self._notify(("state",))
        self._notify(("results",))


__all__ = ["CalcStore", "PREF_PRESETS", "PREF_SECTIONS", "PREF_STATE", "PREF_SWEEP_REGULATION", "PREF_SWEEP_SORT", "SELF_BOOSTS", "best_of", "engine_field", "engine_pokemon", "final_speed", "move_effect", "run", "run_side"]
