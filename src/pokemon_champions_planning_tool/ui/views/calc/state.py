"""Calculator state: two Pokémon, a field, and the results — plain data, JSON round-trippable.

Builders at the bottom turn a team slot, a parsed paste slot or a species id into a
``PokemonState`` so the entry points (Teams, Meta, Box) never touch the engine directly. The
sweep classification (Threat / Wall / …) is here too because it is pure.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from ....domain.species import SpeciesInfo

STATUSES: tuple[tuple[str, str], ...] = (("none", "Healthy"), ("brn", "Burned"), ("psn", "Poisoned"), ("tox", "Badly poisoned"), ("par", "Paralysed"), ("slp", "Asleep"), ("frz", "Frozen"))
WEATHERS: tuple[tuple[str, str], ...] = (("Sun", "Sun"), ("Rain", "Rain"), ("Sand", "Sand"), ("Snow", "Snow"))
TERRAINS: tuple[tuple[str, str], ...] = (("Electric", "Electric Terrain"), ("Grassy", "Grassy Terrain"), ("Psychic", "Psychic Terrain"), ("Misty", "Misty Terrain"))
BOOST_STATS: tuple[str, ...] = ("attack", "defense", "special_attack", "special_defense", "speed")
# Abilities whose on/off state the damage engine reads (``ability_on`` in domain/damage).
# Only these get the panel's "Activate" chip.
TOGGLE_ABILITIES: frozenset[str] = frozenset({
    "Analytic", "Electromorphosis", "Flash Fire", "Intimidate", "Minus", "Plus", "Slow Start", "Unburden",
})
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
    active: list[bool] = field(default_factory=lambda: [False, False, False, False])   # status-move effect applied
    source: str = ""                      # "Team slot 1 · Sun", "Paste", … for the panel caption
    assumptions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> "PokemonState":
        d = dict(data or {})

        def four(values, default):
            out = list(values or [])[:4]
            return out + [default] * (4 - len(out))

        return cls(
            species=d.get("species") or None, nature=str(d.get("nature") or "hardy"), points={k: int(v) for k, v in (d.get("points") or {}).items()},
            ability=d.get("ability") or None, ability_on=bool(d.get("ability_on")), item=d.get("item") or None, status=str(d.get("status") or "none"),
            boosts={k: int(v) for k, v in (d.get("boosts") or {}).items()}, hp_pct=float(d.get("hp_pct", 100.0)), allies_fainted=int(d.get("allies_fainted") or 0),
            moves=[m or None for m in four(d.get("moves"), None)], crit=[bool(c) for c in four(d.get("crit"), False)], active=[bool(a) for a in four(d.get("active"), False)],
            source=str(d.get("source") or ""), assumptions=[str(a) for a in (d.get("assumptions") or [])],
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
    ("reflect", "Reflect"), ("light_screen", "Light Screen"), ("aurora_veil", "Aurora Veil"), ("helping_hand", "Helping Hand"),
    ("friend_guard", "Friend Guard"), ("protect", "Protect"), ("stealth_rock", "Stealth Rock"), ("leech_seed", "Leech Seed"), ("charge", "Charge"), ("power_trick", "Power Trick"),
)
# Side conditions that need an ally on the field: shown, and kept, only in Doubles.
DOUBLES_ONLY: frozenset[str] = frozenset({"helping_hand", "friend_guard"})


@dataclass
class FieldState:
    game_type: str = "doubles"
    weather: str = "none"
    terrain: str = "none"
    gravity: bool = False
    magic_room: bool = False
    wonder_room: bool = False
    trick_room: bool = False              # speed order only (the formula does not read it)
    left: SideConditions = field(default_factory=SideConditions)
    right: SideConditions = field(default_factory=SideConditions)

    @classmethod
    def from_dict(cls, data: dict | None) -> "FieldState":
        d = dict(data or {})
        return cls(
            game_type="singles" if d.get("game_type") == "singles" else "doubles", weather=str(d.get("weather") or "none"), terrain=str(d.get("terrain") or "none"),
            gravity=bool(d.get("gravity")), magic_room=bool(d.get("magic_room")), wonder_room=bool(d.get("wonder_room")), trick_room=bool(d.get("trick_room")),
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
    effectiveness: float | None = None    # type multiplier against the defender (after -ate changes)
    ko_hits: int | None = None            # hits to KO on the average roll (None when it never KOs)

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class CalcResults:
    left_vs_right: tuple[MoveResult, ...] = ()
    right_vs_left: tuple[MoveResult, ...] = ()
    left_name: str = ""
    right_name: str = ""
    left_speed: int = 0                   # final speed under the field (Tailwind, paralysis, Choice Scarf…)
    right_speed: int = 0

    @property
    def empty(self) -> bool:
        return not self.left_vs_right and not self.right_vs_left


@dataclass(frozen=True)
class CalcRequest:
    """Bus payload for ``CALC_REQUESTED``: load one or both sides."""

    attacker: PokemonState | None = None
    defender: PokemonState | None = None


# ------------------------------------------------------------------ opponent sweep

SWEEP_CLASSES: tuple[tuple[str, str], ...] = (("threat", "Threat"), ("wall", "Wall"), ("neutral", "Neutral"), ("mitigated", "Mitigated"), ("crushed", "Crushed"))


@dataclass(frozen=True)
class SweepEntry:
    canonical_id: str
    name: str
    speed: int
    klass: str                            # one of SWEEP_CLASSES keys
    your_best: MoveResult | None          # your strongest move against them
    their_best: MoveResult | None         # their strongest move against you
    faster: bool                          # you move first
    preset: bool                          # their moves came from tournament rosters
    usage_count: int = 0                  # tournament roster count in active regulation


@dataclass(frozen=True)
class TeamRating:
    """One of your team members against the rival in the Defender panel.

    ``klass`` uses ``classify`` from the member's side: "crushed" is good for you,
    "threat" means the rival beats this member.
    """

    slot_key: str                         # "<team id>:<slot position>"
    name: str
    klass: str
    your_best: MoveResult | None          # the member's strongest move against the rival
    their_best: MoveResult | None         # the rival's strongest move against the member
    your_speed: int
    their_speed: int
    faster: bool                          # the member moves first


def hits_to_ko(result: MoveResult | None) -> int | None:
    """Hits on the average roll; None for no damage."""
    if result is None or not result.ok or result.max_pct <= 0:
        return None
    avg = (result.min_pct + result.max_pct) / 2
    return max(1, math.ceil(100 / avg)) if avg > 0 else None


def classify(your_best: MoveResult | None, their_best: MoveResult | None, faster: bool) -> str:
    """Threat class of an opponent versus your attacker.

    - crushed: you KO in one hit and they cannot KO you first (they need two hits, or you are faster)
    - threat: they KO you in one hit before you can, or in two hits while you need three or more
    - wall: you need four hits or more (or never KO) and they are not a threat
    - mitigated: you win the race (fewer hits to KO than they need)
    - neutral: an even race
    """
    yours = hits_to_ko(your_best)
    theirs = hits_to_ko(their_best)
    if yours == 1 and (theirs is None or theirs >= 2 or faster):
        return "crushed"
    if theirs is not None and ((theirs == 1 and (yours is None or yours > 1 or not faster)) or (theirs == 2 and (yours is None or yours >= 3))):
        return "threat"
    if yours is None or yours >= 4:
        return "wall"
    if theirs is None or yours < theirs:
        return "mitigated"
    return "neutral"


# ------------------------------------------------------------------ builders


def _points_app_keys(points: Any) -> dict[str, int]:
    return {str(k): int(v) for k, v in dict(points or {}).items() if int(v) > 0}


def pokemon_from_species_id(canonical_id: str, species: SpeciesInfo | None, *, source: str = "", moves: list[str | None] | None = None) -> PokemonState:
    """A fresh set: first ability, no item, neutral nature, no points."""
    four = list(moves or [])[:4]
    four += [None] * (4 - len(four))
    return PokemonState(species=canonical_id, ability=species.abilities[0] if species and species.abilities else None, source=source, moves=four)


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
        species=built.species.canonical_id, nature=(member.nature or "hardy").lower(), points=_points_app_keys(getattr(member, "points", None)),
        ability=built.pokemon.ability, item=built.pokemon.item or item, moves=moves, source=source, assumptions=list(built.assumptions),
    )


def pokemon_from_parsed(parsed_slot: Any, canonical_id: str, catalogs: Any, *, source: str = "") -> PokemonState | None:
    """From a roster member and, when present, its paste slot (``ParsedSlot``)."""
    from types import SimpleNamespace

    from ....services.damage_calc_service import build_from_roster_member

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
    "BOOST_STATS", "DOUBLES_ONLY", "SIDES", "SIDE_CONDITION_LABELS", "STATUSES", "SWEEP_CLASSES", "TERRAINS", "TOGGLE_ABILITIES", "TeamRating", "WEATHERS", "CalcRequest", "CalcResults", "CalcState",
    "FieldState", "MoveResult", "PokemonState", "SideConditions", "SweepEntry", "classify", "hits_to_ko", "pokemon_from_parsed", "pokemon_from_slot",
    "pokemon_from_species_id",
]
