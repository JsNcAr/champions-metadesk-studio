"""Inputs and working state for the damage engine.

Public inputs (``CalcPokemon``, ``CalcMove``, ``Field``, ``Side``) are frozen. The engine
works on mutable copies (``Mon``, ``MoveState``, ``FieldState``, ``SideState``) exactly like
the reference calculator clones its arguments: mechanics mutate them (Mold Breaker clears an
ability, Intimidate edits boosts, -ate abilities retype the move) and the description and KO
chance read the mutated state afterwards.

Stat keys are the calculator's: ``hp``, ``atk``, ``def``, ``spa``, ``spd``, ``spe``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..moves import MoveInfo, MoveMechanics
from ..stat_calc import NATURES, champions_stat

STATS: tuple[str, ...] = ("hp", "atk", "def", "spa", "spd", "spe")
APP_TO_CALC_STAT: dict[str, str] = {"hp": "hp", "attack": "atk", "defense": "def", "special_attack": "spa", "special_defense": "spd", "speed": "spe"}
CALC_TO_APP_STAT: dict[str, str] = {v: k for k, v in APP_TO_CALC_STAT.items()}
DISPLAY_STAT: dict[str, str] = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}

LEVEL = 50


def nature_plus_minus(nature: str | None) -> tuple[str | None, str | None]:
    """(boosted, hindered) in calc stat keys; neutral or unknown natures give (None, None)."""
    up, down = NATURES.get((nature or "").strip().lower(), (None, None))
    return (APP_TO_CALC_STAT.get(up) if up else None, APP_TO_CALC_STAT.get(down) if down else None)


def nature_mult(nature: str | None, stat: str) -> float:
    up, down = nature_plus_minus(nature)
    if stat == up:
        return 1.1
    if stat == down:
        return 0.9
    return 1.0


def _stats_table(values: Mapping[str, int] | None, default: int) -> dict[str, int]:
    return {k: int((values or {}).get(k, default)) for k in STATS}


# ------------------------------------------------------------------ public inputs


@dataclass(frozen=True)
class CalcPokemon:
    """One combatant. ``name`` is the calculator/Showdown species name ("Charizard-Mega-Y")."""

    name: str
    types: tuple[str, ...]
    base_stats: Mapping[str, int]          # calc keys
    weightkg: float
    ability: str | None = None             # None → first species ability, if ``abilities`` given
    abilities: tuple[str, ...] = ()        # species abilities, first is the default
    ability_on: bool = False
    item: str | None = None
    nature: str | None = None
    points: Mapping[str, int] = field(default_factory=dict)   # calc keys, 0–32, ≤ 66
    boosts: Mapping[str, int] = field(default_factory=dict)   # -6..6
    cur_hp: int | None = None              # None = full
    status: str = ""                       # "", "brn", "psn", "tox", "par", "slp", "frz"
    toxic_counter: int = 0
    allies_fainted: int = 0
    gender: str | None = None              # "M" | "F" | "N"; None → species default → "M"
    level: int = LEVEL

    def raw_stats(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for stat in STATS:
            base = int(self.base_stats.get(stat, 0))
            pts = int(self.points.get(stat, 0))
            out[stat] = champions_stat(base, pts, hp=True) if stat == "hp" else champions_stat(base, pts, nature_mult(self.nature, stat))
        return out


@dataclass(frozen=True)
class CalcMove:
    """A move as the formula sees it (the calculator's ``Move`` after construction)."""

    name: str
    type: str
    category: str                          # "Physical" | "Special" | "Status"
    bp: int
    priority: int = 0
    target: str = "any"
    flags: Mapping[str, int] = field(default_factory=dict)
    secondaries: bool = False
    recoil: tuple[int, int] | None = None
    drain: tuple[int, int] | None = None
    has_crash_damage: bool = False
    mind_blown_recoil: bool = False
    struggle_recoil: bool = False
    ignore_defensive: bool = False
    override_offensive_stat: str | None = None
    override_defensive_stat: str | None = None
    override_offensive_pokemon: str | None = None
    breaks_protect: bool = False
    multiaccuracy: bool = False
    drops_stats: int = 0
    hits: int = 1
    is_crit: bool = False
    times_used: int = 1
    times_used_with_metronome: int = 1
    original_name: str = ""

    @staticmethod
    def resolve_hits(multihit: int | tuple[int, int] | list[int] | None, multiaccuracy: bool, hits: int | None, attacker_ability: str | None) -> int:
        """``move.ts``: fixed multihit wins; a range uses the requested hits, else Skill Link's
        maximum, else the minimum plus one."""
        if not multihit:
            return 1
        if isinstance(multihit, int):
            if multiaccuracy:
                return hits or multihit
            return multihit
        lo, hi = int(multihit[0]), int(multihit[1])
        if hits:
            return hits
        return hi if attacker_ability == "Skill Link" else lo + 1

    @classmethod
    def from_showdown(cls, data: Mapping[str, Any], *, is_crit: bool = False, hits: int | None = None, times_used: int = 1,
                      times_used_with_metronome: int = 1, attacker_ability: str | None = None) -> "CalcMove":
        """Build from Showdown/calculator move JSON (``basePower``, ``flags``, ``multihit`` …)."""
        name = str(data.get("name", ""))
        move_id = str(data.get("id", "")) or name.lower().replace(" ", "").replace("-", "")
        bp = int(data.get("basePower") or 0)
        if not bp and move_id in ("return", "frustration", "pikapapow", "veeveevolley"):
            bp = 102
        category = data.get("category") or "Status"
        self_boosts = ((data.get("self") or {}).get("boosts") or {}) if isinstance(data.get("self"), dict) else {}
        stat = "spa" if category == "Special" else "atk"
        drop = self_boosts.get(stat)
        recoil = data.get("recoil")
        drain = data.get("drain")
        return cls(
            name=name,
            original_name=name,
            type="???" if move_id == "struggle" else str(data.get("type") or "Normal"),
            category=category,
            bp=bp,
            priority=int(data.get("priority") or 0),
            target=str(data.get("target") or "any"),
            flags=dict(data.get("flags") or {}),
            secondaries=bool(data.get("secondaries") or data.get("secondary")),
            recoil=(int(recoil[0]), int(recoil[1])) if recoil else None,
            drain=(int(drain[0]), int(drain[1])) if drain else None,
            has_crash_damage=bool(data.get("hasCrashDamage")),
            mind_blown_recoil=bool(data.get("mindBlownRecoil")),
            struggle_recoil=bool(data.get("struggleRecoil")),
            ignore_defensive=bool(data.get("ignoreDefensive")),
            override_offensive_stat=data.get("overrideOffensiveStat"),
            override_defensive_stat=data.get("overrideDefensiveStat"),
            override_offensive_pokemon=data.get("overrideOffensivePokemon"),
            breaks_protect=bool(data.get("breaksProtect")),
            multiaccuracy=bool(data.get("multiaccuracy")),
            drops_stats=abs(int(drop)) if drop is not None and int(drop) < 0 else 0,
            hits=cls.resolve_hits(data.get("multihit"), bool(data.get("multiaccuracy")), hits, attacker_ability),
            is_crit=bool(is_crit or data.get("willCrit")),
            times_used=times_used or 1,
            times_used_with_metronome=times_used_with_metronome or 1,
        )

    @classmethod
    def from_info(cls, info: MoveInfo, *, is_crit: bool = False, hits: int | None = None, times_used: int = 1,
                  times_used_with_metronome: int = 1, attacker_ability: str | None = None) -> "CalcMove":
        """Build from the app's move catalogue entry."""
        m: MoveMechanics = info.mechanics
        data: dict[str, Any] = {
            "id": info.move_id, "name": info.name, "type": (info.type or "Normal").capitalize(), "category": (info.category or "Status").capitalize(),
            "basePower": info.power or 0, "priority": info.priority, "target": info.target or "any",
            "flags": {k: 1 for k in ("contact", "sound", "punch", "bite", "bullet", "pulse", "slicing", "wind") if getattr(m, k)},
            "secondaries": m.secondaries, "recoil": m.recoil, "drain": m.drain, "multihit": m.multihit, "multiaccuracy": m.multiaccuracy,
            "willCrit": m.will_crit, "ignoreDefensive": m.ignore_defensive, "overrideOffensiveStat": m.override_offensive_stat,
            "overrideDefensiveStat": m.override_defensive_stat, "overrideOffensivePokemon": m.override_offensive_pokemon,
            "breaksProtect": m.breaks_protect, "hasCrashDamage": m.has_crash_damage, "struggleRecoil": m.struggle_recoil,
            "mindBlownRecoil": m.mind_blown_recoil, "self": {"boosts": dict(m.self_boosts)} if m.self_boosts else None,
        }
        return cls.from_showdown(data, is_crit=is_crit, hits=hits, times_used=times_used, times_used_with_metronome=times_used_with_metronome, attacker_ability=attacker_ability)


@dataclass(frozen=True)
class Side:
    spikes: int = 0
    is_sr: bool = False
    is_reflect: bool = False
    is_light_screen: bool = False
    is_protected: bool = False
    is_seeded: bool = False
    is_nightmared: bool = False
    is_salt_cured: bool = False
    is_charge: bool = False
    is_tailwind: bool = False
    is_helping_hand: bool = False
    is_power_trick: bool = False
    is_friend_guard: bool = False
    is_aurora_veil: bool = False
    is_switching: str | None = None        # "out" | "in"


@dataclass(frozen=True)
class Field:
    game_type: str = "Singles"             # "Singles" | "Doubles"
    weather: str | None = None             # "Sun" | "Rain" | "Sand" | "Snow" | "Hail" | "Harsh Sunshine" | "Heavy Rain"
    terrain: str | None = None             # "Electric" | "Grassy" | "Psychic" | "Misty"
    is_magic_room: bool = False
    is_wonder_room: bool = False
    is_gravity: bool = False
    is_fairy_aura: bool = False
    is_dark_aura: bool = False
    attacker_side: Side = field(default_factory=Side)
    defender_side: Side = field(default_factory=Side)


# ------------------------------------------------------------------ working state


@dataclass
class Mon:
    name: str
    types: list[str]
    base_stats: dict[str, int]
    weightkg: float
    level: int
    gender: str
    ability: str | None
    ability_on: bool
    item: str | None
    nature: str | None
    points: dict[str, int]
    boosts: dict[str, int]
    raw_stats: dict[str, int]
    stats: dict[str, int]
    original_cur_hp: int
    status: str
    toxic_counter: int
    allies_fainted: int
    disabled_item: str | None = None

    @classmethod
    def from_input(cls, p: CalcPokemon) -> "Mon":
        raw = p.raw_stats()
        ability = p.ability or (p.abilities[0] if p.abilities else None)
        cur = p.cur_hp if p.cur_hp is not None and p.cur_hp <= raw["hp"] else raw["hp"]
        return cls(
            name=p.name, types=list(p.types), base_stats=dict(p.base_stats), weightkg=float(p.weightkg), level=p.level,
            gender=p.gender or "M", ability=ability, ability_on=bool(p.ability_on), item=p.item or None, nature=p.nature,
            points=_stats_table(p.points, 0), boosts=_stats_table(p.boosts, 0), raw_stats=raw, stats=dict(raw),
            original_cur_hp=cur, status=p.status or "", toxic_counter=int(p.toxic_counter or 0), allies_fainted=int(p.allies_fainted or 0),
        )

    def clone(self) -> "Mon":
        """Like ``Pokemon.clone()``: rebuilt from the same inputs, so raw stats are recomputed."""
        p = CalcPokemon(
            name=self.name, types=tuple(self.types), base_stats=self.base_stats, weightkg=self.weightkg, ability=self.ability,
            ability_on=self.ability_on, item=self.item, nature=self.nature, points=self.points, boosts=dict(self.boosts),
            cur_hp=self.original_cur_hp, status=self.status, toxic_counter=self.toxic_counter, allies_fainted=self.allies_fainted,
            gender=self.gender, level=self.level,
        )
        m = Mon.from_input(p)
        m.ability = self.ability  # '' after Mold Breaker stays ''
        return m

    def max_hp(self) -> int:
        return self.raw_stats["hp"]

    def cur_hp(self) -> int:
        return self.original_cur_hp

    def has_ability(self, *abilities: str) -> bool:
        return bool(self.ability) and self.ability in abilities

    def has_item(self, *items: str) -> bool:
        return bool(self.item) and self.item in items

    def has_status(self, *statuses: str) -> bool:
        return bool(self.status) and self.status in statuses

    def has_type(self, *types: str) -> bool:
        return any(t in self.types for t in types)

    def has_original_type(self, *types: str) -> bool:
        return self.has_type(*types)

    def named(self, *names: str) -> bool:
        return self.name in names


@dataclass
class MoveState:
    name: str
    original_name: str
    type: str
    category: str
    bp: int
    priority: int
    target: str
    flags: dict[str, int]
    secondaries: bool
    recoil: tuple[int, int] | None
    drain: tuple[int, int] | None
    has_crash_damage: bool
    mind_blown_recoil: bool
    struggle_recoil: bool
    ignore_defensive: bool
    override_offensive_stat: str | None
    override_defensive_stat: str | None
    override_offensive_pokemon: str | None
    breaks_protect: bool
    multiaccuracy: bool
    drops_stats: int
    hits: int
    is_crit: bool
    times_used: int
    times_used_with_metronome: int

    @classmethod
    def from_input(cls, m: CalcMove) -> "MoveState":
        return cls(
            name=m.name, original_name=m.original_name or m.name, type=m.type, category=m.category, bp=m.bp, priority=m.priority, target=m.target,
            flags=dict(m.flags), secondaries=m.secondaries, recoil=m.recoil, drain=m.drain, has_crash_damage=m.has_crash_damage,
            mind_blown_recoil=m.mind_blown_recoil, struggle_recoil=m.struggle_recoil, ignore_defensive=m.ignore_defensive,
            override_offensive_stat=m.override_offensive_stat, override_defensive_stat=m.override_defensive_stat,
            override_offensive_pokemon=m.override_offensive_pokemon, breaks_protect=m.breaks_protect, multiaccuracy=m.multiaccuracy,
            drops_stats=m.drops_stats, hits=m.hits, is_crit=m.is_crit, times_used=m.times_used, times_used_with_metronome=m.times_used_with_metronome,
        )

    def named(self, *names: str) -> bool:
        return self.name in names

    def has_type(self, *types: str | None) -> bool:
        return self.type in types


@dataclass
class SideState:
    spikes: int = 0
    is_sr: bool = False
    is_reflect: bool = False
    is_light_screen: bool = False
    is_protected: bool = False
    is_seeded: bool = False
    is_nightmared: bool = False
    is_salt_cured: bool = False
    is_charge: bool = False
    is_tailwind: bool = False
    is_helping_hand: bool = False
    is_power_trick: bool = False
    is_friend_guard: bool = False
    is_aurora_veil: bool = False
    is_switching: str | None = None

    @classmethod
    def from_input(cls, s: Side) -> "SideState":
        return cls(**{k: getattr(s, k) for k in cls.__dataclass_fields__})


@dataclass
class FieldState:
    game_type: str
    weather: str | None
    terrain: str | None
    is_magic_room: bool
    is_wonder_room: bool
    is_gravity: bool
    is_fairy_aura: bool
    is_dark_aura: bool
    attacker_side: SideState
    defender_side: SideState

    @classmethod
    def from_input(cls, f: Field) -> "FieldState":
        return cls(
            game_type=f.game_type, weather=f.weather, terrain=f.terrain, is_magic_room=f.is_magic_room, is_wonder_room=f.is_wonder_room,
            is_gravity=f.is_gravity, is_fairy_aura=f.is_fairy_aura, is_dark_aura=f.is_dark_aura,
            attacker_side=SideState.from_input(f.attacker_side), defender_side=SideState.from_input(f.defender_side),
        )

    def has_weather(self, *weathers: str) -> bool:
        return bool(self.weather) and self.weather in weathers

    def has_terrain(self, *terrains: str) -> bool:
        return bool(self.terrain) and self.terrain in terrains
