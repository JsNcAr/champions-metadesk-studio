"""Pokémon Showdown GitHub raw file client.

Fetches TypeScript data files from the official smogon/pokemon-showdown
repository. Parses item legality and Mega Stone mappings using regex — this
avoids a heavy JS/TS parser dependency while being robust against the stable
structural patterns in Showdown's data files.

All fetch results are cached in-memory with lru_cache, consistent with
the pokeapi_retrieval.py pattern established in this project.
"""

from __future__ import annotations

import re
from functools import lru_cache

import requests

from ...config import POKEAPI_TIMEOUT_SECONDS

# ---------------------------------------------------------------------------
# GitHub raw content URLs — only these two files are needed
# ---------------------------------------------------------------------------
_SHOWDOWN_BASE = (
    "https://raw.githubusercontent.com/smogon/pokemon-showdown/master"
)
_BASE_ITEMS_URL = f"{_SHOWDOWN_BASE}/data/items.ts"
_CHAMPIONS_ITEMS_URL = f"{_SHOWDOWN_BASE}/data/mods/champions/items.ts"


# ---------------------------------------------------------------------------
# Low-level fetchers (lru_cached so repeated calls in a session are 0ms)
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _fetch_base_items_ts() -> str:
    """Downloads data/items.ts from Showdown GitHub. Cached per process."""
    try:
        response = requests.get(_BASE_ITEMS_URL, timeout=POKEAPI_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Showdown: Could not fetch base items.ts: {e}")
        return ""


@lru_cache(maxsize=1)
def _fetch_champions_items_ts() -> str:
    """Downloads data/mods/champions/items.ts from Showdown GitHub. Cached per process."""
    try:
        response = requests.get(_CHAMPIONS_ITEMS_URL, timeout=POKEAPI_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Showdown: Could not fetch champions/items.ts: {e}")
        return ""


# ---------------------------------------------------------------------------
# Parsers — operate on the cached text strings, no further I/O
# ---------------------------------------------------------------------------

def _extract_item_blocks(ts_text: str) -> dict[str, str]:
    """Extracts top-level item blocks from a Showdown TypeScript items file.

    Uses brace-depth tracking to correctly handle nested objects (like megaStone)
    and function bodies (like onTakeItem). Returns {slug: block_body_text}.
    """
    # Find the start of the export object
    export_start = ts_text.find("{", ts_text.find("export const Items"))
    if export_start == -1:
        return {}

    result: dict[str, str] = {}
    slug_pattern = re.compile(r"^(?:\t| {1,4})([a-z0-9]+):\s*\{", re.MULTILINE)
    text_from_export = ts_text[export_start + 1:]

    for match in slug_pattern.finditer(text_from_export):
        slug = match.group(1)
        block_start = match.end() - 1  # position of the opening {

        # Walk forward tracking brace depth to find matching closing brace
        depth = 0
        i = block_start
        while i < len(text_from_export):
            ch = text_from_export[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    result[slug] = text_from_export[block_start + 1:i]
                    break
            i += 1

    return result


@lru_cache(maxsize=1)
def get_champions_legal_slugs() -> set[str]:
    """Returns the set of item slugs legal in Pokémon Champions format.

    Resolution logic (mirrors how Showdown's mod system works):
      1. Start with base items.ts — any item with no isNonstandard is legal.
      2. Apply champions/items.ts overrides:
         - isNonstandard: "Past"  → mark as illegal (banned in Champions)
         - isNonstandard: null    → override a "Past" entry back to legal
    """
    base_text = _fetch_base_items_ts()
    champions_text = _fetch_champions_items_ts()

    if not base_text:
        return set()

    base_blocks = _extract_item_blocks(base_text)
    champions_blocks = _extract_item_blocks(champions_text) if champions_text else {}

    def _get_nonstandard(body: str) -> str | None:
        m = re.search(r"isNonstandard:\s*([^\n,}]+)", body)
        return m.group(1).strip().strip("\"'") if m else None

    legal_slugs: set[str] = set()

    for slug, body in base_blocks.items():
        base_nonstandard = _get_nonstandard(body)

        if slug in champions_blocks:
            override = _get_nonstandard(champions_blocks[slug])
            if override == "null":
                # Explicitly re-legalized in Champions (e.g. Mega Stones)
                legal_slugs.add(slug)
            elif override is not None and "Past" in override:
                # Explicitly banned in Champions
                pass
            else:
                # No override change — use base legality
                if base_nonstandard is None:
                    legal_slugs.add(slug)
        else:
            # Not mentioned in Champions mod — use base legality
            if base_nonstandard is None:
                legal_slugs.add(slug)

    return legal_slugs


@lru_cache(maxsize=1)
def get_mega_stone_mappings() -> dict[str, dict[str, str]]:
    """Returns {showdown_slug: {species, form, mega_stone_name}} for all Mega Stones.

    Example:
        {"charizarditex": {"species": "charizard", "form": "mega-x", "mega_stone_name": "Charizard-Mega-X"}}
    """
    base_text = _fetch_base_items_ts()
    if not base_text:
        return {}

    blocks = _extract_item_blocks(base_text)
    mappings: dict[str, dict[str, str]] = {}

    # megaStone has the form: megaStone: { "Species": "Species-Mega-Form" }
    mega_stone_pattern = re.compile(
        r'megaStone:\s*\{\s*"([^"]+)":\s*"([^"]+)"\s*\}'
    )

    for slug, body in blocks.items():
        m = mega_stone_pattern.search(body)
        if m:
            species_raw = m.group(1)   # e.g. "Charizard"
            form_raw = m.group(2)       # e.g. "Charizard-Mega-X"

            species_slug = species_raw.lower()
            lower_form = form_raw.lower()
            if lower_form.endswith("-mega-x"):
                form_slug = "mega-x"
            elif lower_form.endswith("-mega-y"):
                form_slug = "mega-y"
            else:
                form_slug = "mega"

            mappings[slug] = {
                "species": species_slug,
                "form": form_slug,
                "mega_stone_name": form_raw,
            }

    return mappings


def parse_item_spritenums(*texts: str) -> dict[str, int]:
    """{item slug: spritenum} from Showdown item files; later files override earlier ones."""
    pattern = re.compile(r"spritenum:\s*(\d+)")
    out: dict[str, int] = {}
    for text in texts:
        if not text:
            continue
        for slug, body in _extract_item_blocks(text).items():
            m = pattern.search(body)
            if m:
                out[slug] = int(m.group(1))
    return out


@lru_cache(maxsize=1)
def get_item_spritenums() -> dict[str, int]:
    """{item slug: cell on Showdown's item sheet}, the Champions mod over the base file."""
    return parse_item_spritenums(_fetch_base_items_ts(), _fetch_champions_items_ts())


def clear_showdown_cache() -> None:
    """Evicts all lru_cache entries so the next call re-fetches from GitHub.

    Call this when the user triggers a manual 'Sync Items' refresh.
    """
    _fetch_base_items_ts.cache_clear()
    _fetch_champions_items_ts.cache_clear()
    get_champions_legal_slugs.cache_clear()
    get_mega_stone_mappings.cache_clear()
    get_item_spritenums.cache_clear()
