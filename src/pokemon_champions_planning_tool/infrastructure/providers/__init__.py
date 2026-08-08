"""Hybrid item provider — combines Showdown legality with PokéAPI metadata.

This is the single entry point that services use to get item data. It:
  1. Fetches Champions-legal slugs and Mega Stone mappings from Showdown (1 HTTP call, cached).
  2. Fetches base item display data (name, sprite, short_effect, category) from PokéAPI.
  3. Merges them into ItemRecord instances ready for SQLite persistence.

Services NEVER import ShowdownItemAdapter or the PokéAPI client directly.
"""

from __future__ import annotations

import re

import requests

from ....config import POKEAPI_BASE_URL, POKEAPI_TIMEOUT_SECONDS
from ...domain.entities.item import Item
from ..database.models import ItemRecord
from ..showdown.showdown_adapter import ShowdownItemAdapter

# ---------------------------------------------------------------------------
# Known stat modifier map — applied at sync time, zero extra network calls
# ---------------------------------------------------------------------------
_STAT_MODIFIER_MAP: dict[str, dict[str, float]] = {
    "choicescarf":  {"speed": 1.5},
    "choiceband":   {"attack": 1.5},
    "choicespecs":  {"special_attack": 1.5},
    "lifeorb":      {"attack": 1.3, "special_attack": 1.3},
    "ironball":     {"speed": 0.5},
}

# Normalise Showdown compact slug to PokéAPI hyphenated slug
# (e.g. "choicescarf" -> "choice-scarf", "charizarditex" -> "charizardite-x")
# Most can be derived by inserting hyphens before uppercase transitions, but
# Showdown slugs are already lowercase-concatenated, so we maintain a small
# explicit map for the irregular ones we know about.
_SHOWDOWN_TO_POKEAPI_SLUG: dict[str, str] = {
    "choicescarf": "choice-scarf",
    "choiceband":  "choice-band",
    "choicespecs": "choice-specs",
    "lifeorb":     "life-orb",
    "ironball":    "iron-ball",
    "zoomlens":    "zoom-lens",
    "assaultvest": "assault-vest",
    "eviolite":    "eviolite",
    "leftovers":   "leftovers",
}


def _showdown_slug_to_pokeapi(slug: str) -> str:
    """Converts a Showdown compact slug to a PokéAPI hyphenated slug.

    Uses the explicit map for known items, otherwise inserts hyphens at
    digit-to-letter and letter-to-digit boundaries (handles most Mega Stones
    like "charizarditex" -> "charizardite-x").
    """
    if slug in _SHOWDOWN_TO_POKEAPI_SLUG:
        return _SHOWDOWN_TO_POKEAPI_SLUG[slug]
    # Insert hyphen before trailing single letters/digits (mega stone suffixes)
    # e.g. charizarditex -> charizardite-x, charizarditey -> charizardite-y
    converted = re.sub(r"([a-z])([xy])$", r"\1-\2", slug)
    return converted


def _fetch_pokeapi_item_detail(pokeapi_slug: str) -> dict | None:
    """Fetches a single item's display metadata from PokéAPI. Returns None on error."""
    try:
        url = f"{POKEAPI_BASE_URL}/item/{pokeapi_slug}"
        res = requests.get(url, timeout=POKEAPI_TIMEOUT_SECONDS)
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return res.json()
    except requests.exceptions.RequestException as e:
        print(f"⚠️ PokéAPI: Could not fetch item '{pokeapi_slug}': {e}")
        return None


def _build_item_record(
    showdown_slug: str,
    is_champions_legal: bool,
    mega_mappings: dict[str, dict[str, str]],
    pokeapi_data: dict | None,
) -> ItemRecord:
    """Assembles an ItemRecord from Showdown legality + optional PokéAPI metadata."""
    pokeapi_slug = _showdown_slug_to_pokeapi(showdown_slug)

    display_name = pokeapi_slug.replace("-", " ").title()
    category = "other"
    sprite_url = None
    short_effect = ""

    if pokeapi_data:
        # Best English name
        for name_entry in pokeapi_data.get("names", []):
            if name_entry.get("language", {}).get("name") == "en":
                display_name = name_entry["name"]
                break
        category = pokeapi_data.get("category", {}).get("name", "other")
        sprite_url = pokeapi_data.get("sprites", {}).get("default")
        # Best English short effect
        for effect_entry in pokeapi_data.get("effect_entries", []):
            if effect_entry.get("language", {}).get("name") == "en":
                short_effect = effect_entry.get("short_effect", "")
                break

    # Mega Stone links from Showdown data
    mega_info = mega_mappings.get(showdown_slug)
    target_species = mega_info["species"] if mega_info else None
    target_form = mega_info["form"] if mega_info else None

    # Stat modifiers from local map
    stat_modifiers = _STAT_MODIFIER_MAP.get(showdown_slug, {})

    return ItemRecord(
        canonical_id=pokeapi_slug,
        display_name=display_name,
        category=category,
        is_champions_legal=is_champions_legal,
        sprite_url=sprite_url,
        short_effect=short_effect,
        target_species=target_species,
        target_form=target_form,
        stat_modifiers=stat_modifiers,
    )


class HybridItemProvider:
    """Merges Showdown legality data with PokéAPI display metadata.

    Intended to be instantiated once and reused across the sync service.
    """

    def __init__(self, showdown_adapter: ShowdownItemAdapter | None = None):
        self._showdown = showdown_adapter or ShowdownItemAdapter()

    def fetch_item_records(
        self,
        existing_pokeapi_slugs: set[str],
        skip_pokeapi: bool = False,
    ) -> list[ItemRecord]:
        """Fetches and merges item records from both sources.

        Args:
            existing_pokeapi_slugs: PokéAPI slugs already in the local DB.
                Only items NOT in this set trigger a PokéAPI detail fetch.
            skip_pokeapi: If True, builds records from Showdown data only
                (no network calls to PokéAPI). Useful for fast staleness checks.

        Returns:
            List of ItemRecord instances ready for upsert into SQLite.
        """
        legal_slugs = self._showdown.fetch_champions_legal_item_slugs()
        mega_mappings = self._showdown.fetch_mega_stone_mappings()

        # Collect all items Showdown knows about (legal + mega stones that
        # were overridden to null = legal, even if base was Past)
        all_showdown_slugs = legal_slugs | set(mega_mappings.keys())

        records: list[ItemRecord] = []
        for showdown_slug in sorted(all_showdown_slugs):
            is_legal = showdown_slug in legal_slugs
            pokeapi_slug = _showdown_slug_to_pokeapi(showdown_slug)

            # Skip PokéAPI fetch if record already in DB
            pokeapi_data = None
            if not skip_pokeapi and pokeapi_slug not in existing_pokeapi_slugs:
                pokeapi_data = _fetch_pokeapi_item_detail(pokeapi_slug)

            records.append(
                _build_item_record(showdown_slug, is_legal, mega_mappings, pokeapi_data)
            )

        return records

    def get_champions_legal_count(self) -> int:
        """Returns the current count of Champions-legal slugs from Showdown (0 = offline)."""
        return len(self._showdown.fetch_champions_legal_item_slugs())

    def clear_cache(self) -> None:
        """Evicts all Showdown in-memory caches for manual refresh."""
        self._showdown.clear_cache()
