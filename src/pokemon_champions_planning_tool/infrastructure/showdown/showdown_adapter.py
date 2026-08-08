"""Pokémon Showdown adapter — implements ItemCatalogProvider port.

Wraps the raw showdown_client functions and exposes them under the
ItemCatalogProvider interface. This is the only file that imports
showdown_client; all other application code goes through this adapter
or the HybridItemProvider.
"""

from __future__ import annotations

from . import (
    clear_showdown_cache,
    get_champions_legal_slugs,
    get_mega_stone_mappings,
)


class ShowdownItemAdapter:
    """Adapter that satisfies the ItemCatalogProvider protocol using Showdown data.

    Structurally satisfies domain/interfaces/ItemCatalogProvider via
    typing.Protocol — no explicit inheritance needed.
    """

    # ------------------------------------------------------------------
    # ItemCatalogProvider protocol methods
    # ------------------------------------------------------------------

    def fetch_champions_legal_item_slugs(self) -> set[str]:
        """Returns the set of Showdown compact-slugs legal in Pokémon Champions.

        Note: Showdown uses compact slugs without hyphens (e.g. 'choicescarf').
        The HybridItemProvider is responsible for normalising these to PokéAPI
        hyphenated slugs when hydrating ItemRecord entries.
        """
        return get_champions_legal_slugs()

    def fetch_mega_stone_mappings(self) -> dict[str, dict[str, str]]:
        """Returns {showdown_slug: {species, form, mega_stone_name}} for all Mega Stones."""
        return get_mega_stone_mappings()

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Evicts all in-memory caches so the next call re-fetches from GitHub."""
        clear_showdown_cache()
