"""PokéAPI adapter for Pokemon stat retrieval."""

import requests

from config import POKEAPI_BASE_URL, POKEAPI_TIMEOUT_SECONDS
from domain.pokemon_identity import format_display_name, format_api_name


def get_official_stats(pokemon_name):
    """Fetches stats directly from PokéAPI using requests."""
    api_name = format_api_name(pokemon_name)

    if not api_name:
        return None

    try:
        url = f"{POKEAPI_BASE_URL}/pokemon/{api_name}"
        response = requests.get(url, timeout=POKEAPI_TIMEOUT_SECONDS)
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

        # TODO: Handle multiple abilities
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
