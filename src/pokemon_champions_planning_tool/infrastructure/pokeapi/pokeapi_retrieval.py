"""PokéAPI adapter for Pokemon stat retrieval."""

import requests

from ...config import POKEAPI_BASE_URL, POKEAPI_TIMEOUT_SECONDS
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.pokemon_ability import PokemonAbility
from ...domain.entities.pokemon_stats import PokemonStats
from ...domain.pokemon_identity import format_display_name, format_api_name


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

        stats = {stat['stat']['name']: stat['base_stat']
                 for stat in pokemon_data['stats']}
        hp = stats.get('hp', 0)
        atk = stats.get('attack', 0)
        dfn = stats.get('defense', 0)
        spa = stats.get('special-attack', 0)
        spd = stats.get('special-defense', 0)
        spe = stats.get('speed', 0)

        abilities = [
            PokemonAbility(
                name=ability_data["ability"]["name"],
                slot=ability_data.get("slot"),
                is_hidden=ability_data.get("is_hidden", False),
                url=ability_data["ability"].get("url"),
            )
            for ability_data in pokemon_data.get('abilities', [])
        ]

        form = "Base"
        if "mega" in api_name:
            form = "Mega"
        elif any(region in api_name for region in ["alola", "galar", "hisui", "paldea"]):
            form = "Regional"

        return Pokemon(
            canonical_id=api_name,
            display_name=format_display_name(api_name),
            species_name=pokemon_data.get("species", {}).get("name"),
            form_name=form,
            dex_number=pokemon_data.get("id"),
            types=[type_data["type"]["name"] for type_data in pokemon_data.get("types", [])],
            sprite_url=pokemon_data.get("sprites", {}).get("front_default"),
            stats=PokemonStats(
                hp=hp,
                attack=atk,
                defense=dfn,
                sp_atk=spa,
                sp_def=spd,
                speed=spe,
            ),
            abilities=abilities,
            moves=[],
            available_forms=[],
        )

    except requests.exceptions.HTTPError as http_err:
        if response.status_code == 404:
            return None
        print(f"⚠️ HTTP error occurred: {http_err}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error reaching PokéAPI: {e}")
        return None
