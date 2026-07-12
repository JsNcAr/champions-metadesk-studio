"""Use-case orchestration for adding a Pokemon to the CSV box."""

from config import DEFAULT_CSV_FILENAME
from infrastructure.csv.csv_operations import upsert_to_spreadsheet
from infrastructure.pokeapi.pokeapi_retrieval import (
    get_official_stats,
)


def append_to_spreadsheet(pokemon_name, filename=DEFAULT_CSV_FILENAME):
    formatted_name = pokemon_name.strip().title()
    if not formatted_name:
        return

    print(f"🔍 Querying PokéAPI endpoint for '{formatted_name}'...")
    official_data = get_official_stats(formatted_name)

    if official_data:
        upsert_to_spreadsheet(official_data, filename)
        print(f"✅ Success: Saved '{official_data['display_name']}' to CSV.")
    else:
        print(
            f"❌ Error: '{formatted_name}' could not be found. Check your spelling.")
