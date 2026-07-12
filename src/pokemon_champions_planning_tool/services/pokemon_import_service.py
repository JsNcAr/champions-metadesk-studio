"""Use-case orchestration for adding a Pokemon to the CSV box."""

from ..config import DEFAULT_CSV_FILENAME
from ..domain.entities.box_entry import BoxEntry
from ..infrastructure.csv.csv_operations import export_box_entries_to_csv
from ..infrastructure.database.database import get_session
from ..infrastructure.database.repositories import BoxRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import (
    get_official_stats,
)


def add_pokemon_to_box(pokemon_name, filename=DEFAULT_CSV_FILENAME):
    formatted_name = pokemon_name.strip().title()
    if not formatted_name:
        return

    print(f"🔍 Querying PokéAPI endpoint for '{formatted_name}'...")
    official_data = get_official_stats(formatted_name)

    if official_data:
        with get_session() as session:
            box_repository = BoxRepository(session)
            box_repository.upsert_box_entry(BoxEntry(pokemon=official_data))
            export_box_entries_to_csv(box_repository.list_entries(), filename)

        print(f"✅ Success: Saved '{official_data.display_name}' to SQLite and CSV.")
    else:
        print(
            f"❌ Error: '{formatted_name}' could not be found. Check your spelling.")


append_to_spreadsheet = add_pokemon_to_box
