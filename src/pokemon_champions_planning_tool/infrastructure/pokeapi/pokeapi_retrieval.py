"""PokéAPI adapter for Pokemon stat retrieval."""

from functools import lru_cache
import requests

from ...config import POKEAPI_BASE_URL, POKEAPI_TIMEOUT_SECONDS
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.pokemon_ability import PokemonAbility
from ...domain.entities.pokemon_stats import PokemonStats
from ...domain.pokemon_identity import format_display_name, format_api_name
from ..database.models import MegaEvolutionRecord


@lru_cache(maxsize=512)
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


@lru_cache(maxsize=16)
def get_champions_pokedex_species(pokedex_name: str = "champions") -> list[dict]:
    """Fetches the list of species in the specified Pokédex (defaults to 'champions') from PokéAPI."""
    try:
        url = f"{POKEAPI_BASE_URL}/pokedex/{pokedex_name}"
        response = requests.get(url, timeout=POKEAPI_TIMEOUT_SECONDS)
        response.raise_for_status()

        data = response.json()
        entries = []
        for entry in data.get("pokemon_entries", []):
            species_info = entry.get("pokemon_species", {})
            raw_name = species_info.get("name", "")
            if raw_name:
                entries.append({
                    "entry_number": entry.get("entry_number", 0),
                    "species_name": raw_name,
                    "display_name": format_display_name(raw_name),
                })
        return entries
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error fetching {pokedex_name} Pokédex catalog: {e}")
        return []


@lru_cache(maxsize=512)
def get_mega_varieties_for_species(species_name: str) -> list[str]:
    """Fetches the list of Mega variety canonical IDs for a species from PokéAPI."""
    try:
        url = f"{POKEAPI_BASE_URL}/pokemon-species/{species_name.strip().lower()}"
        response = requests.get(url, timeout=POKEAPI_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        varieties = data.get("varieties", [])
        mega_names = []
        for var in varieties:
            v_name = var.get("pokemon", {}).get("name", "")
            if "-mega" in v_name:
                mega_names.append(v_name)
        return mega_names
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error checking Mega varieties for '{species_name}': {e}")
        return []


@lru_cache(maxsize=256)
def get_official_mega_details(mega_api_name: str) -> MegaEvolutionRecord | None:
    """Fetches details for a specific Mega Evolution from PokéAPI and builds a MegaEvolutionRecord."""
    try:
        url = f"{POKEAPI_BASE_URL}/pokemon/{mega_api_name.strip().lower()}"
        response = requests.get(url, timeout=POKEAPI_TIMEOUT_SECONDS)
        response.raise_for_status()

        data = response.json()
        stats = {stat["stat"]["name"]: stat["base_stat"] for stat in data.get("stats", [])}

        species_name = data.get("species", {}).get("name", mega_api_name.split("-mega")[0])
        display_name = format_display_name(mega_api_name)

        return MegaEvolutionRecord(
            canonical_id=mega_api_name,
            species_name=species_name,
            display_name=display_name,
            form_name="Mega X" if mega_api_name.endswith("-mega-x") else "Mega Y" if mega_api_name.endswith("-mega-y") else "Mega",
            types=[t["type"]["name"] for t in data.get("types", [])],
            sprite_url=data.get("sprites", {}).get("front_default"),
            hp=stats.get("hp", 0),
            attack=stats.get("attack", 0),
            defense=stats.get("defense", 0),
            special_attack=stats.get("special-attack", 0),
            special_defense=stats.get("special-defense", 0),
            speed=stats.get("speed", 0),
        )
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error fetching Mega details for '{mega_api_name}': {e}")
        return None


