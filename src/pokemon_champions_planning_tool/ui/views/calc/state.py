"""Calculator state: two Pokémon, a field, and the results — plain data, JSON round-trippable.

Builders at the bottom turn a team slot, a parsed paste slot or a species id into a
``PokemonState`` so the entry points (Teams, Meta, Box) never touch the engine directly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from ....domain.species import SpeciesInfo

STATUSES: tuple[tuple[str, str], ...] = (("none", "Healthy"), ("brn", "Burned"), ("psn", "Poisoned"), ("tox", "Badly poisoned"), ("par", "Paralysed"), ("slp", "Asleep"), ("frz", "Frozen"))
WEATHERS: tuple[tuple[str, str], ...] = (("none", "No weather"), ("Sun", "Sun"), ("Rain", "Rain"), ("Sand", "Sandstorm"), ("Snow", "Snow"))
TERRAINS: tuple[tuple[str, str], ...] = (("none", "No terrain"), ("Electric", "Electric Terrain"), ("Grassy", "Grassy Terrain"), ("Psychic", "Psychic Terrain"), ("Misty", "Misty Terrain"))
BOOST_STATS: tuple[str, ...] = ("attack", "defense", "special_attack", "special_defense", "speed")
SIDES: tuple[str, str] = ("left", "right")


@dataclass
class PokemonState:
    species: str | None = None            # canonical id, mega forms included ("charizard-mega-y")
    nature: str = "hardy"
    points: dict[str, int] = field(default_factory=dict)   # app stat keys
    ability: str | None = None
    ability_on: bool = False
    item: str | None = None               # display name, as the calculator spells it
    status: str = "none"
    boosts: dict[str, int] = field(default_factory=dict)   # app stat keys, -6..6
    hp_pct: float = 100.0
    allies_fainted: int = 0
    moves: list[str | None] = field(default_factory=lambda: [None, None, None, None])
    crit: list[bool] = field(default_factory=lambda: [False, False, False, False])
    source: str = ""                      # "Team slot 1 · Sun", "Paste", … for the panel caption
    assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> "PokemonState":
        d = dict(data or {})
        moves = list(d.get("moves") or [])[:4]
        moves += [None] * (4 - len(moves))
        crit = [bool(c) for c in (d.get("crit") or [])][:4]
        crit += [False] * (4 - len(crit))
        return cls(
            species=d.get("species") or None, nature=str(d.get("nature") or "hardy"), points={k: int(v) for k, v in (d.get("points") or {}).items()},
            ability=d.get("ability") or None, ability_on=bool(d.get("ability_on")), item=d.get("item") or None, status=str(d.get("status") or "none"),
            boosts={k: int(v) for k, v in (d.get("boosts") or {}).items()}, hp_pct=float(d.get("hp_pct", 100.0)), allies_fainted=int(d.get("allies_fainted") or 0),
            moves=[m or None for m in moves], crit=crit, source=str(d.get("source") or ""), assumptions=[str(a) for a in (d.get("assumptions") or [])],
        )


@dataclass
class SideConditions:
    reflect: bool = False
    light_screen: bool = False
    aurora_veil: bool = False
    tailwind: bool = False
    helping_hand: bool = False
    friend_guard: bool = False
    protect: bool = False
    stealth_rock: bool = False
    spikes: int = 0
    leech_seed: bool = False
    charge: bool = False
    power_trick: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "SideConditions":
        d = dict(data or {})
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: (int(v) if k == "spikes" else bool(v)) for k, v in d.items() if k in known}
        return cls(**kwargs)


SIDE_CONDITION_LABELS: tuple[tuple[str, str], ...] = (
    ("reflect", "Reflect"), ("light_screen", "Light Screen"), ("aurora_veil", "Aurora Veil"), ("tailwind", "Tailwind"), ("helping_hand", "Helping Hand"),
    ("friend_guard", "Friend Guard"), ("protect", "Protect"), ("stealth_rock", "Stealth Rock"), ("leech_seed", "Leech Seed"), ("charge", "Charge"), ("power_trick", "Power Trick"),
)


@dataclass
class FieldState:
    game_type: str = "doubles"
    weather: str = "none"
    terrain: str = "none"
    gravity: bool = False
    magic_room: bool = False
    wonder_room: bool = False
    left: SideConditions = field(default_factory=SideConditions)
    right: SideConditions = field(default_factory=SideConditions)

    @classmethod
    def from_dict(cls, data: dict | None) -> "FieldState":
        d = dict(data or {})
        return cls(
            game_type="singles" if d.get("game_type") == "singles" else "doubles", weather=str(d.get("weather") or "none"), terrain=str(d.get("terrain") or "none"),
            gravity=bool(d.get("gravity")), magic_room=bool(d.get("magic_room")), wonder_room=bool(d.get("wonder_room")),
            left=SideConditions.from_dict(d.get("left")), right=SideConditions.from_dict(d.get("right")),
        )


@dataclass
class CalcState:
    left: PokemonState = field(default_factory=PokemonState)
    right: PokemonState = field(default_factory=PokemonState)
    field: FieldState = field(default_factory=FieldState)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "CalcState":
        d = dict(data or {})
        return cls(left=PokemonState.from_dict(d.get("left")), right=PokemonState.from_dict(d.get("right")), field=FieldState.from_dict(d.get("field")))

    def key(self) -> str:
        """Cache key: every input that changes a result (captions and assumptions excluded)."""
        d = self.to_dict()
        for side in SIDES:
            d[side].pop("source", None)
            d[side].pop("assumptions", None)
        return json.dumps(d, sort_keys=True)

    def side(self, side: str) -> PokemonState:
        return self.left if side == "left" else self.right

    def with_side(self, side: str, pokemon: PokemonState) -> "CalcState":
        return replace(self, left=pokemon) if side == "left" else replace(self, right=pokemon)


@dataclass(frozen=True)
class MoveResult:
    index: int
    name: str
    type: str | None
    category: str | None
    min_dmg: int
    max_dmg: int
    min_pct: float
    max_pct: float
    rolls: tuple[int, ...]
    description: str
    ko_text: str
    recoil: str | None = None
    recovery: str | None = None
    error: str | None = None
    bp: int | float | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class CalcResults:
    left_vs_right: tuple[MoveResult, ...] = ()
    right_vs_left: tuple[MoveResult, ...] = ()
    left_name: str = ""
    right_name: str = ""

    @property
    def empty(self) -> bool:
        return not self.left_vs_right and not self.right_vs_left


@dataclass(frozen=True)
class CalcRequest:
    """Bus payload for ``CALC_REQUESTED``: load one or both sides."""

    attacker: PokemonState | None = None
    defender: PokemonState | None = None


# ------------------------------------------------------------------ builders


def _points_app_keys(points: Any) -> dict[str, int]:
    return {str(k): int(v) for k, v in dict(points or {}).items() if int(v) > 0}


def pokemon_from_species_id(canonical_id: str, species: SpeciesInfo | None, *, source: str = "") -> PokemonState:
    """A fresh set: first ability, no item, neutral nature, no points."""
    return PokemonState(species=canonical_id, ability=species.abilities[0] if species and species.abilities else None, source=source)


def pokemon_from_slot(slot: Any, catalogs: Any, *, source: str = "") -> PokemonState | None:
    """From a team ``SlotModel``: mega form, item, ability, moves, points and nature."""
    from ....services.damage_calc_service import build_from_slot

    built = build_from_slot(slot, catalogs)
    if built is None:
        return None
    member = slot.member
    moves = [m.name for m in (member.moveset or []) if getattr(m, "name", None)][:4]
    moves += [None] * (4 - len(moves))
    item = slot.item.display_name if getattr(slot, "item", None) is not None else (built.pokemon.item or None)
    return PokemonState(
        species=built.species.canonical_id if catalogs.species_for(built.species.canonical_id) else built.species.canonical_id,
        nature=(member.nature or "hardy").lower(), points=_points_app_keys(getattr(member, "points", None)),
        ability=built.pokemon.ability, item=built.pokemon.item or item, moves=moves, source=source, assumptions=list(built.assumptions),
    )


def pokemon_from_parsed(parsed_slot: Any, canonical_id: str, catalogs: Any, *, source: str = "") -> PokemonState | None:
    """From a roster member and, when present, its paste slot (``ParsedSlot``)."""
    from ....services.damage_calc_service import build_from_roster_member
    from types import SimpleNamespace

    built = build_from_roster_member(SimpleNamespace(canonical_id=canonical_id, species_name=""), parsed_slot, catalogs)
    if built is None:
        return None
    moves = [m for m in (getattr(parsed_slot, "moves", ()) or ()) if m][:4] if parsed_slot is not None else []
    moves += [None] * (4 - len(moves))
    nature = (getattr(parsed_slot, "nature", None) or "hardy").lower() if parsed_slot is not None else "hardy"
    return PokemonState(
        species=built.species.canonical_id, nature=nature, points=_points_app_keys(getattr(parsed_slot, "points", None) if parsed_slot is not None else None),
        ability=built.pokemon.ability, item=built.pokemon.item, moves=moves, source=source, assumptions=list(built.assumptions),
    )


__all__ = [
    "BOOST_STATS", "SIDES", "SIDE_CONDITION_LABELS", "STATUSES", "TERRAINS", "WEATHERS", "CalcRequest", "CalcResults", "CalcState", "FieldState",
    "MoveResult", "PokemonState", "SideConditions", "pokemon_from_parsed", "pokemon_from_slot", "pokemon_from_species_id",
]
