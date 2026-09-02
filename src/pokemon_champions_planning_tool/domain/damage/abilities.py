"""Ability names and the ability groups the Champions mechanics test against."""

from __future__ import annotations

import re
from functools import lru_cache

from .items import _reference_data

_NON_ALNUM = re.compile(r"[^a-z0-9]")

# Abilities Mold Breaker ignores (the reference's list, verbatim).
MOLD_BREAKER_IGNORED: tuple[str, ...] = (
    "Armor Tail", "Aroma Veil", "Battle Armor", "Big Pecks", "Bulletproof", "Clear Body", "Contrary", "Damp", "Disguise", "Dry Skin",
    "Earth Eater", "Eelevate", "Filter", "Flash Fire", "Flower Veil", "Fluffy", "Friend Guard", "Fur Coat", "Heatproof", "Heavy Metal",
    "Hyper Cutter", "Illuminate", "Immunity", "Inner Focus", "Insomnia", "Keen Eye", "Leaf Guard", "Levitate", "Light Metal",
    "Lightning Rod", "Limber", "Magic Bounce", "Magma Armor", "Marvel Scale", "Mirror Armor", "Motor Drive", "Multiscale", "Oblivious",
    "Overcoat", "Own Tempo", "Purifying Salt", "Queenly Majesty", "Sand Veil", "Sap Sipper", "Shell Armor", "Shield Dust", "Snow Cloak",
    "Solid Rock", "Soundproof", "Sticky Hold", "Storm Drain", "Sturdy", "Sweet Veil", "Tangled Feet", "Telepathy", "Thick Fat", "Unaware",
    "Vital Spirit", "Volt Absorb", "Water Absorb", "Water Bubble", "Water Veil", "White Smoke",
)

INTIMIDATE_BLOCKERS: tuple[str, ...] = ("Clear Body", "White Smoke", "Hyper Cutter", "Full Metal Body", "Inner Focus", "Own Tempo", "Oblivious", "Scrappy")
ATE_ABILITIES: tuple[str, ...] = ("Aerilate", "Dragonize", "Pixilate", "Refrigerate")


@lru_cache(maxsize=1)
def ability_names() -> tuple[str, ...]:
    """Every ability the Champions calculator knows (200), in the reference's order."""
    return tuple(_reference_data().get("abilities", []))


@lru_cache(maxsize=1)
def _index() -> dict[str, str]:
    return {_NON_ALNUM.sub("", n.lower()): n for n in ability_names()}


def canonical_ability_name(raw: str | None) -> str | None:
    """"lightning-rod", "Lightning rod" or "lightningrod" → "Lightning Rod"; unknown names are
    title-cased so the engine at least compares a consistent spelling."""
    if not raw:
        return None
    key = _NON_ALNUM.sub("", raw.lower())
    if key in _index():
        return _index()[key]
    return raw.replace("-", " ").strip().title()
