"""Move catalogue types and the species-key rules that tie our identifiers to Showdown's.

Showdown keys a learnset by a lowercase alphanumeric species key ("urshifurapidstrike",
"rotomwash"); our canonical ids are PokéAPI slugs ("urshifu-rapid-strike",
"charizard-mega-y"). Mega forms use the base species' learnset in Champions, and a form
Showdown does not key separately ("basculegion-male") falls back to its base.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from .pokemon_identity import base_canonical_id  # re-exported: callers import it from here too

_NON_ALNUM = re.compile(r"[^a-z0-9]")


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
