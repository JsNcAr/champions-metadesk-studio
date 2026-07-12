import csv
import os

from ...config import CSV_HEADERS, DEFAULT_CSV_FILENAME
from ...domain.entities.pokemon import Pokemon
from ...domain.pokemon_identity import format_api_name

def load_existing_rows(filename):
    if not os.path.isfile(filename):
        return []

    with open(filename, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [row for row in reader if any(row.values())]


def save_rows(filename, rows):
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def _build_row(pokemon: Pokemon):
    return {
        "Pokémon": pokemon.display_name,
        "Form": pokemon.form_name,
        "Ability": pokemon.abilities[0].name.title().replace("-", " ") if pokemon.abilities else "Unknown",
        "HP": pokemon.stats.hp,
        "Attack": pokemon.stats.attack,
        "Defense": pokemon.stats.defense,
        "Sp. Atk": pokemon.stats.special_attack,
        "Sp. Def": pokemon.stats.special_defense,
        "Speed": pokemon.stats.speed,
        "Total": pokemon.total,
    }


def upsert_to_spreadsheet(official_data, filename=DEFAULT_CSV_FILENAME):
    existing_rows = load_existing_rows(filename)
    updated_rows = []
    seen = False

    if isinstance(official_data, Pokemon):
        canonical_id = official_data.canonical_id
        row_data = _build_row(official_data)
    else:
        canonical_id = official_data["api_name"]
        row_data = {
            "Pokémon": official_data["display_name"],
            "Form": official_data["form"],
            "Ability": official_data["ability"],
            "HP": official_data["hp"],
            "Attack": official_data["attack"],
            "Defense": official_data["defense"],
            "Sp. Atk": official_data["sp_atk"],
            "Sp. Def": official_data["sp_def"],
            "Speed": official_data["speed"],
            "Total": official_data["total"],
        }

    for row in existing_rows:
        existing_key = format_api_name(row.get("Pokémon") or "")
        if existing_key == canonical_id:
            if not seen:
                updated_rows.append(row_data)
                seen = True
            continue

        updated_rows.append(row)

    if not seen:
        updated_rows.append(row_data)

    save_rows(filename, updated_rows)
