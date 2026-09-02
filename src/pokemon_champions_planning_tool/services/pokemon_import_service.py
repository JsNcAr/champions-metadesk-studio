"""Use case: add a Pokémon to the box by name.

Looks the species up in the local cache first and falls back to PokéAPI. Returns the
resulting box entry; callers decide about side effects such as the CSV export.
"""

from __future__ import annotations

from ..domain.entities.box_entry import BoxEntry
from ..domain.entities.pokemon import Pokemon
from ..domain.pokemon_identity import format_api_name
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import BoxRepository, PokemonRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import PokeApiUnavailable, get_official_stats


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
        official_data = existing_record.to_domain() if existing_record else None
        # A stored record is reused only when it carries real data. Team imports may have
        # written a placeholder (no types, zero stats) for a species that was not in the
        # box; that must never come back as "the" Pokémon.
        if official_data is None or official_data.is_stub:
            try:
                fetched = get_official_stats(formatted_name)
            except PokeApiUnavailable:
                if official_data is None:
                    raise
                fetched = None  # keep the marked placeholder; the repair pass retries later
            if fetched:
                pokemon_repo.upsert(fetched)
                official_data = fetched

        if not official_data:
            raise PokemonNotFoundError(f"'{formatted_name}' could not be found — check the spelling")

        record = box_repo.upsert_box_entry(BoxEntry(pokemon=official_data), allow_placeholder=official_data.is_stub)
        entry = box_repo.load_entry(str(record.box_entry_id))
        if entry is None:  # pragma: no cover - the entry was just written
            raise PokemonNotFoundError(f"'{formatted_name}' was not saved")
        return entry


def refresh_pokemon_record(canonical_id: str, display_name: str | None = None) -> Pokemon | None:
    """Re-fetch one species from PokéAPI and replace its stored record; None when offline."""
    try:
        fetched = get_official_stats(display_name or canonical_id.replace("-", " ").title())
    except PokeApiUnavailable:
        return None
    if not fetched:
        return None
    with get_session() as session:
        PokemonRepository(session).upsert(fetched)
    return fetched


def refresh_stub_pokemon(session) -> dict:
    """Repair pass: re-fetch every placeholder record still referenced by a box entry.

    Runs at startup; only species with placeholder data touch the network, so a healthy
    box costs nothing. Returns {"stubs": N, "repaired": M}.
    """
    box_repo = BoxRepository(session)
    pokemon_repo = PokemonRepository(session)
    stubs = {e.pokemon.canonical_id: e.pokemon.display_name for e in box_repo.list_entries(include_planned=True) if e.pokemon.is_stub}
    repaired = 0
    for canonical_id, display_name in stubs.items():
        try:
            fetched = get_official_stats(display_name) or get_official_stats(canonical_id)
        except PokeApiUnavailable as exc:
            print(f"⚠️ Box data repair paused: {exc}")
            break  # the network is the problem, not the name: stop asking
        if fetched:
            pokemon_repo.upsert(fetched)
            repaired += 1
    if stubs:
        print(f"{'✅' if repaired == len(stubs) else '⚠️'} Box data repair: {repaired} of {len(stubs)} placeholder Pokémon re-fetched.")
    return {"stubs": len(stubs), "repaired": repaired}


# Kept for the terminal shell, which reports and exports the CSV itself.
append_to_spreadsheet = add_pokemon_to_box
