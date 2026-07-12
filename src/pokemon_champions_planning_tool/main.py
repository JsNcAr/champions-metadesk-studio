import csv
import os
import requests


HEADERS = ["Pokémon", "Form", "Ability", "HP", "Attack",
           "Defense", "Sp. Atk", "Sp. Def", "Speed", "Total"]


def format_display_name(api_name):
    """Converts a PokéAPI identifier into a consistent display name."""
    if not api_name:
        return ""

    if api_name.endswith("-mega-x"):
        return f"Mega {api_name.removesuffix('-mega-x').title()} X"
    if api_name.endswith("-mega-y"):
        return f"Mega {api_name.removesuffix('-mega-y').title()} Y"
    if api_name.endswith("-mega"):
        return f"Mega {api_name.removesuffix('-mega').title()}"

    regional_labels = {
        "alola": "Alolan",
        "galar": "Galarian",
        "hisui": "Hisuian",
        "paldea": "Paldean",
    }
    for region, label in regional_labels.items():
        suffix = f"-{region}"
        if api_name.endswith(suffix):
            return f"{label} {api_name.removesuffix(suffix).title()}"

    return api_name.title()


def format_api_name(pokemon_name):
    """
    Translates human-readable names into PokéAPI's internal URL format.
    Example: "Mega Raichu X" -> "raichu-mega-x"
    """
    words = pokemon_name.strip().lower().split()

    if not words:
        return ""

    # Handle Mega Evolutions
    if words[0] == "mega":
        if len(words) == 3 and words[2] in ['x', 'y']:
            return f"{words[1]}-mega-{words[2]}"
        elif len(words) == 2:
            return f"{words[1]}-mega"

    # Handle Regional Forms (e.g., "Hisuian Typhlosion" -> "typhlosion-hisui")
    if words[0] in ["alolan", "galarian", "hisuian", "paldean"]:
        # Strip the 'n' suffix to match API regional tags
        region = words[0][:-1] if words[0].endswith('n') else words[0]
        return f"{words[1]}-{region}"

    # Default behavior for standard Pokémon
    return "-".join(words)


def get_official_stats(pokemon_name):
    """Fetches stats directly from PokéAPI using requests."""
    api_name = format_api_name(pokemon_name)

    if not api_name:
        return None

    try:
        url = f"https://pokeapi.co/api/v2/pokemon/{api_name}"
        response = requests.get(url, timeout=5)
        response.raise_for_status()

        pokemon_data = response.json()

        # Extract base stats
        stats = {stat['stat']['name']: stat['base_stat']
                 for stat in pokemon_data['stats']}
        hp = stats.get('hp', 0)
        atk = stats.get('attack', 0)
        dfn = stats.get('defense', 0)
        spa = stats.get('special-attack', 0)
        spd = stats.get('special-defense', 0)
        spe = stats.get('speed', 0)
        total = hp + atk + dfn + spa + spd + spe

        # Grab primary ability
        abilities = pokemon_data.get('abilities', [])
        ability = abilities[0]['ability']['name'].title().replace(
            "-", " ") if abilities else "Unknown"

        # Detect Form for the spreadsheet column
        form = "Base"
        if "mega" in api_name:
            form = "Mega"
        elif any(region in api_name for region in ["alola", "galar", "hisui", "paldea"]):
            form = "Regional"

        return {
            "api_name": api_name,
            "display_name": format_display_name(api_name),
            "form": form,
            "ability": ability,
            "hp": hp,
            "attack": atk,
            "defense": dfn,
            "sp_atk": spa,
            "sp_def": spd,
            "speed": spe,
            "total": total,
        }

    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 404:
            return None
        print(f"⚠️ HTTP error occurred: {http_err}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error reaching PokéAPI: {e}")
        return None


def load_existing_rows(filename):
    if not os.path.isfile(filename):
        return []

    with open(filename, mode="r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return [row for row in reader if any(row.values())]


def save_rows(filename, rows):
    with open(filename, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def upsert_to_spreadsheet(official_data, filename="pokemon_team_stats.csv"):
    existing_rows = load_existing_rows(filename)
    updated_rows = []
    seen = False

    for row in existing_rows:
        existing_key = format_api_name(row.get("Pokémon") or "")
        if existing_key == official_data["api_name"]:
            if not seen:
                updated_rows.append({
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
                })
                seen = True
            continue

        updated_rows.append(row)

    if not seen:
        updated_rows.append({
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
        })

    save_rows(filename, updated_rows)


def append_to_spreadsheet(pokemon_name, filename="pokemon_team_stats.csv"):
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


if __name__ == "__main__":
    print("=" * 44)
    print("  Live PokéAPI Data Pipeline Automator  ")
    print("=" * 44)
    print("Type 'exit' or 'quit' at any time to close.\n")

    while True:
        user_input = input("Enter Pokémon Name: ").strip()
        if user_input.lower() in ['exit', 'quit']:
            print("Shutting down data pipeline...")
            break
        append_to_spreadsheet(user_input)
