"""Use case: add a Pokémon to the box by name.

Looks the species up in the local cache first and falls back to PokéAPI. Returns the
resulting box entry; callers decide about side effects such as the CSV export.
"""

from __future__ import annotations

from ..domain.entities.box_entry import BoxEntry
from ..domain.pokemon_identity import format_api_name
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import BoxRepository, PokemonRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import get_official_stats


class PokemonNotFoundError(LookupError):
    """The name did not resolve locally or on PokéAPI."""


def add_pokemon_to_box(pokemon_name: str) -> BoxEntry:
    """Add ``pokemon_name`` to the box and return the stored entry.

    Raises ``ValueError`` for a blank name and ``PokemonNotFoundError`` when neither the
    local catalogue nor PokéAPI knows the species. Network errors propagate.
    """
    formatted_name = (pokemon_name or "").strip().title()
    if not formatted_name:
        raise ValueError("Enter a Pokémon name")

    api_name = format_api_name(formatted_name)

    with get_session() as session:
        pokemon_repo = PokemonRepository(session)
        box_repo = BoxRepository(session)

        existing_record = pokemon_repo.get(api_name) if api_name else None
        if existing_record:
            official_data = existing_record.to_domain()
        else:
            official_data = get_official_stats(formatted_name)
            if official_data:
                pokemon_repo.upsert(official_data)

        if not official_data:
            raise PokemonNotFoundError(f"'{formatted_name}' could not be found — check the spelling")

        record = box_repo.upsert_box_entry(BoxEntry(pokemon=official_data))
        entry = box_repo.load_entry(str(record.box_entry_id))
        if entry is None:  # pragma: no cover - the entry was just written
            raise PokemonNotFoundError(f"'{formatted_name}' was not saved")
        return entry


# Kept for the terminal shell, which reports and exports the CSV itself.
append_to_spreadsheet = add_pokemon_to_box
