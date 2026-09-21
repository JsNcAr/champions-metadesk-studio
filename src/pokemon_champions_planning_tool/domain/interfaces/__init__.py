"""Domain-level port interfaces (abstract contracts) for external data providers.

These protocols define *what* data the application needs without specifying
*how* or *where* it is retrieved. Services and UI code depend only on these
protocols — never on PokéAPI or Showdown client code directly.

Using typing.Protocol (structural subtyping) means adapters do NOT need to
explicitly inherit from these interfaces. Any class that implements the
correct methods qualifies, which makes mocking in tests trivial.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable



@runtime_checkable
class ItemCatalogProvider(Protocol):
    """Port for retrieving item catalog data and Champions format legality."""

    def fetch_champions_legal_item_slugs(self) -> set[str]:
        """Returns the set of item slugs legal in Pokémon Champions format.

        Items NOT in this set should be shown with a warning in the UI.
        An empty set means the source could not be reached (treat as unknown).
        """
        ...

    def fetch_mega_stone_mappings(self) -> dict[str, dict[str, str]]:
        """Returns a mapping of mega stone slug -> target species and form.

        Example output:
            {
                "charizardite-x": {"species": "charizard", "form": "mega-x"},
                "blastoisite":    {"species": "blastoise",  "form": "mega"},
            }
        An empty dict means the source could not be reached.
        """
        ...
