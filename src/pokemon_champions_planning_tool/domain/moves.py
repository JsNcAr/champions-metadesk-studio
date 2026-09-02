"""Move catalogue types and the species-key rules that tie our identifiers to Showdown's.

Showdown keys a learnset by a lowercase alphanumeric species key ("urshifurapidstrike",
"rotomwash"); our canonical ids are PokéAPI slugs ("urshifu-rapid-strike",
"charizard-mega-y"). Mega forms use the base species' learnset in Champions, and a form
Showdown does not key separately ("basculegion-male") falls back to its base.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import re
from collections.abc import Iterable
from dataclasses import dataclass, fields

from .pokemon_identity import base_canonical_id  # re-exported: callers import it from here too

_NON_ALNUM = re.compile(r"[^a-z0-9]")


@dataclass(frozen=True)
class MoveMechanics:
    """The Showdown move fields the damage formula needs beyond power/type/category.

    Stored as JSON on the move catalogue (non-default keys only); every field defaults to
    "nothing special" so older catalogues still load.
    """

    contact: bool = False
    sound: bool = False
    punch: bool = False
    bite: bool = False
    bullet: bool = False
    pulse: bool = False
    slicing: bool = False
    wind: bool = False
    secondaries: bool = False               # has a secondary effect (Sheer Force)
    recoil: tuple[int, int] | None = None   # (numerator, denominator) of damage dealt
    drain: tuple[int, int] | None = None
    multihit: int | tuple[int, int] | None = None
    multiaccuracy: bool = False
    will_crit: bool = False
    crit_ratio: int = 0
    ignore_defensive: bool = False
    override_offensive_stat: str | None = None     # "def" (Body Press)
    override_defensive_stat: str | None = None     # "def" (Psyshock)
    override_offensive_pokemon: str | None = None  # "target" (Foul Play)
    breaks_protect: bool = False
    has_crash_damage: bool = False
    struggle_recoil: bool = False
    mind_blown_recoil: bool = False
    self_boosts: tuple[tuple[str, int], ...] = ()  # raw ``self.boosts`` in calc stat keys
    ohko: bool = False

    _FLAGS = ("contact", "sound", "punch", "bite", "bullet", "pulse", "slicing", "wind")

    def drops_stats(self, category: str | None) -> int:
        stat = "spa" if (category or "").lower() == "special" else "atk"
        for key, value in self.self_boosts:
            if key == stat and value < 0:
                return abs(int(value))
        return 0

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            value = getattr(self, f.name)
            if value == f.default:
                continue
            if isinstance(value, tuple):
                value = [list(v) if isinstance(v, tuple) else v for v in value]
            out[f.name] = value
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, Any] | None) -> "MoveMechanics":
        if not data:
            return cls()
        kwargs: dict[str, Any] = {}
        names = {f.name for f in fields(cls)}
        for key, value in data.items():
            if key not in names:
                continue
            if key in ("recoil", "drain") and value is not None:
                value = (int(value[0]), int(value[1]))
            elif key == "multihit" and isinstance(value, list):
                value = (int(value[0]), int(value[1]))
            elif key == "self_boosts":
                value = tuple((str(k), int(v)) for k, v in value)
            kwargs[key] = value
        return cls(**kwargs)


@dataclass(frozen=True)
class MoveInfo:
    """One move as the picker and legality checks see it."""

    move_id: str
    name: str
    type: str | None
    category: str | None
    power: int | None
    accuracy: int | None
    pp: int | None
    priority: int
    target: str | None
    short_desc: str | None
    is_legal: bool  # False for moves Champions removed from the game entirely
    mechanics: MoveMechanics = MoveMechanics()


def move_key(name: str | None) -> str:
    """Showdown's move id: lowercase, alphanumeric only ("Fake Out" -> "fakeout")."""
    return _NON_ALNUM.sub("", (name or "").lower())


def showdown_species_key(canonical_id: str | None) -> str:
    return _NON_ALNUM.sub("", base_canonical_id(canonical_id))


def resolve_learnset_key(canonical_id: str | None, available: Iterable[str]) -> str | None:
    """The learnset key for a species, or None when the catalogue has nothing for it.

    Tries the full form first, then drops trailing hyphen segments so that a form
    Showdown does not key separately ("basculegion-male", "tauros-paldea-combat-breed")
    resolves to the nearest keyed ancestor.
    """
    keys = set(available)
    base = base_canonical_id(canonical_id)
    parts = base.split("-")
    while parts:
        key = _NON_ALNUM.sub("", "-".join(parts))
        if key in keys:
            return key
        parts.pop()
    return None


__all__ = ["MoveInfo", "base_canonical_id", "move_key", "resolve_learnset_key", "showdown_species_key"]
