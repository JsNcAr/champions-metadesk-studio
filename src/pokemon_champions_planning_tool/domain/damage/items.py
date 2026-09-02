"""Item mechanics for the damage engine, mirroring the calculator's ``items.ts`` restricted to
Pokémon Champions' item pool. Names are the calculator's ("Never-Melt Ice", "King's Rock").
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from importlib import resources

_NON_ALNUM = re.compile(r"[^a-z0-9]")


def _key(name: str | None) -> str:
    return _NON_ALNUM.sub("", (name or "").lower())


# Type-boosting held items (×1.2 base power on moves of the type).
ITEM_BOOST_TYPE: dict[str, str] = {
    "Dragon Fang": "Dragon", "Black Glasses": "Dark", "Soft Sand": "Ground", "Black Belt": "Fighting", "Charcoal": "Fire",
    "Never-Melt Ice": "Ice", "Silver Powder": "Bug", "Metal Coat": "Steel", "Miracle Seed": "Grass", "Twisted Spoon": "Psychic",
    "Fairy Feather": "Fairy", "Sharp Beak": "Flying", "Mystic Water": "Water", "Spell Tag": "Ghost", "Hard Stone": "Rock",
    "Poison Barb": "Poison", "Magnet": "Electric", "Silk Scarf": "Normal",
}

# Damage-halving berries (super-effective hits, or any Normal hit for Chilan).
BERRY_RESIST_TYPE: dict[str, str] = {
    "Chilan Berry": "Normal", "Occa Berry": "Fire", "Passho Berry": "Water", "Wacan Berry": "Electric", "Rindo Berry": "Grass",
    "Yache Berry": "Ice", "Chople Berry": "Fighting", "Kebia Berry": "Poison", "Shuca Berry": "Ground", "Coba Berry": "Flying",
    "Payapa Berry": "Psychic", "Tanga Berry": "Bug", "Charti Berry": "Rock", "Kasib Berry": "Ghost", "Haban Berry": "Dragon",
    "Colbur Berry": "Dark", "Babiri Berry": "Steel", "Roseli Berry": "Fairy",
}

# Fling base power for the items Champions has (``getFlingPower`` for gen 9 rules).
_FLING: dict[str, int] = {
    "Iron Ball": 130, "Hard Stone": 100, "Quick Claw": 80, "Dragon Fang": 70, "Poison Barb": 70, "Damp Rock": 60, "Heat Rock": 60,
    "Sharp Beak": 50, "Icy Rock": 40, "Black Belt": 30, "Black Glasses": 30, "Charcoal": 30,
    "Choice Scarf": 10, "Expert Belt": 10, "Focus Band": 10, "Focus Sash": 10, "Leftovers": 10, "Mental Herb": 10, "Muscle Band": 10,
    "Shed Shell": 10, "Silk Scarf": 10, "Silver Powder": 10, "Smooth Rock": 10, "Soft Sand": 10, "White Herb": 10, "Wide Lens": 10,
    "Wise Glasses": 10, "Zoom Lens": 10,
}

# Items whose speed drop Klutz does not disable (only Iron Ball exists in Champions).
EV_ITEMS: tuple[str, ...] = ("Macho Brace", "Power Anklet", "Power Band", "Power Belt", "Power Bracer", "Power Lens", "Power Weight")


def item_boost_type(item: str | None) -> str | None:
    return ITEM_BOOST_TYPE.get(item or "")


def berry_resist_type(item: str | None) -> str | None:
    return BERRY_RESIST_TYPE.get(item or "")


def fling_power(item: str | None) -> int:
    if not item:
        return 0
    if item in _FLING:
        return _FLING[item]
    if "Plate" in item:
        return 90
    if "Berry" in item:
        return 10
    return 0


@lru_cache(maxsize=1)
def _reference_data() -> dict:
    """The calculator's Champions item/ability/mega-stone tables, dumped by the fixture generator."""
    try:
        text = resources.files("pokemon_champions_planning_tool.domain.damage").joinpath("reference_data.json").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return {"items": [], "abilities": [], "mega_stones": {}}
    return json.loads(text)


@lru_cache(maxsize=1)
def champions_items() -> frozenset[str]:
    return frozenset(i["name"] for i in _reference_data().get("items", []))


@lru_cache(maxsize=1)
def mega_stones() -> dict[str, dict[str, str]]:
    """Stone → {base species name: mega name}; used for Knock Off's resistance check."""
    return {k: dict(v) for k, v in _reference_data().get("mega_stones", {}).items()}


@lru_cache(maxsize=1)
def _item_index() -> dict[str, str]:
    index = {_key(n): n for n in champions_items()}
    for n in list(ITEM_BOOST_TYPE) + list(BERRY_RESIST_TYPE) + list(_FLING):
        index.setdefault(_key(n), n)
    return index


def canonical_item_name(raw: str | None) -> str | None:
    """Map "life-orb", "Life orb", "lifeorb" or a PokéAPI display name to the calculator's
    spelling. Unknown names are returned unchanged (an item with no effect)."""
    if not raw:
        return None
    return _item_index().get(_key(raw), raw.strip())


def resists_knock_off(item: str | None, holder_name: str) -> bool:
    """A Mega Stone matching its holder (or an already-Mega holder) is not knocked off."""
    stone = mega_stones().get(item or "")
    if not stone:
        return False
    return holder_name in stone or holder_name in stone.values()
