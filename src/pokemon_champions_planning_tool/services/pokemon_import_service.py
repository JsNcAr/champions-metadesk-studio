"""Use-case orchestration for adding a Pokemon to the CSV box."""

from ..config import DEFAULT_CSV_FILENAME
from ..domain.entities.box_entry import BoxEntry
from ..domain.pokemon_identity import format_api_name
from ..infrastructure.csv.csv_operations import export_box_entries_to_csv
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import BoxRepository, PokemonRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import get_official_stats


def add_pokemon_to_box(pokemon_name, filename=DEFAULT_CSV_FILENAME):
    formatted_name = pokemon_name.strip().title()
    if not formatted_name:
        return

    api_name = format_api_name(formatted_name)

    with get_session() as session:
        pokemon_repo = PokemonRepository(session)
        box_repo = BoxRepository(session)

        # 1. Check local SQLite cache first (0ms latency)
        existing_record = pokemon_repo.get(api_name) if api_name else None
        if existing_record:
            official_data = existing_record.to_domain()
        else:
            print(f"🔍 Querying PokéAPI endpoint for '{formatted_name}'...")
            official_data = get_official_stats(formatted_name)
            if official_data:
                pokemon_repo.upsert(official_data)

        if official_data:
            box_repo.upsert_box_entry(BoxEntry(pokemon=official_data))
            export_box_entries_to_csv(box_repo.list_entries(), filename)
            print(f"✅ Success: Saved '{official_data.display_name}' to SQLite and CSV.")
        else:
            print(f"❌ Error: '{formatted_name}' could not be found. Check your spelling.")


append_to_spreadsheet = add_pokemon_to_box

