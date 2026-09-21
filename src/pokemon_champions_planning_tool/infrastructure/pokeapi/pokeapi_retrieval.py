"""PokéAPI adapter for Pokemon stat retrieval."""

from functools import lru_cache
import requests

from ...config import POKEAPI_BASE_URL, POKEAPI_TIMEOUT_SECONDS
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.pokemon_ability import PokemonAbility
from ...domain.entities.pokemon_stats import PokemonStats
from ...domain.pokemon_identity import (
    SHOWDOWN_TO_POKEAPI_SLUG,
    default_form_label,
    format_api_name,
    format_display_name,
)
from ...domain.species import CANONICAL_ALIASES
from ..database.models import MegaEvolutionRecord


class PokeApiUnavailable(Exception):
    """PokéAPI could not answer (offline, timeout, throttled). Distinct from "not found"."""


def _get_json(url: str) -> dict | None:
    """GET ``url``; the parsed body, None on 404, ``PokeApiUnavailable`` on anything else."""
    try:
        response = requests.get(url, timeout=POKEAPI_TIMEOUT_SECONDS)
        if response.status_code == 404:
            return None  # genuinely unknown name
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        raise PokeApiUnavailable(f"PokéAPI answered {response.status_code} — it may be throttling; try again in a minute") from http_err
    except requests.exceptions.RequestException as e:
        raise PokeApiUnavailable(f"PokéAPI is unreachable: {e}") from e


def _default_variety(species_slug: str) -> str | None:
    """The ``/pokemon/`` slug of a species' default form, or None when the species is unknown.

    Ten Champions species have no ``/pokemon/<species>`` entry because their default form
    carries a suffix: basculegion → basculegion-male, aegislash → aegislash-shield,
    lycanroc → lycanroc-midday, mimikyu → mimikyu-disguised, and so on.
    """
    data = _get_json(f"{POKEAPI_BASE_URL}/pokemon-species/{species_slug}")
    if not data:
        return None
    for variety in data.get("varieties", []):
        if variety.get("is_default"):
            return variety.get("pokemon", {}).get("name")
    return None


@lru_cache(maxsize=512)
def get_official_stats(pokemon_name):
    """Fetch a Pokémon from PokéAPI.

    Returns None when the name is unknown and raises ``PokeApiUnavailable`` when PokéAPI
    cannot answer. A species whose default form lives under a suffixed slug is fetched
    through that form but keeps the species slug as its id, so it lines up with the
    Champions catalogue, tournament rosters and learnsets.
    """
    api_name = format_api_name(pokemon_name)

    if not api_name:
        return None

    # Map Showdown canonical slug to PokéAPI variety slug if they differ
    poke_slug = SHOWDOWN_TO_POKEAPI_SLUG.get(api_name, api_name)

    pokemon_data = _get_json(f"{POKEAPI_BASE_URL}/pokemon/{poke_slug}")
    if pokemon_data is None:
        variety = _default_variety(poke_slug)
        pokemon_data = _get_json(f"{POKEAPI_BASE_URL}/pokemon/{variety}") if variety and variety != poke_slug else None
        if pokemon_data is None and poke_slug != api_name:
            variety = _default_variety(api_name)
            pokemon_data = _get_json(f"{POKEAPI_BASE_URL}/pokemon/{variety}") if variety and variety != api_name else None
        if pokemon_data is None:
            return None

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

    canon_id = CANONICAL_ALIASES.get(api_name, api_name)
    form = default_form_label(canon_id)
    if not form:
        if canon_id.endswith(("-f", "-female")):
            form = "Female"
        elif "mega" in canon_id:
            form = "Mega"
        elif any(region in canon_id for region in ["alola", "galar", "hisui", "paldea"]):
            form = "Regional"
        else:
            form = "Base"

    return Pokemon(
        canonical_id=canon_id,
        display_name=format_display_name(canon_id),
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
        parsed_abilities = [format_display_name(a["ability"]["name"]) for a in data.get("abilities", []) if a.get("ability")]
        ability = parsed_abilities[0] if parsed_abilities else ""

        return MegaEvolutionRecord(
            canonical_id=mega_api_name,
            species_name=species_name,
            display_name=display_name,
            form_name=next((label for suffix, label in (("-mega-x", "Mega X"), ("-mega-y", "Mega Y"), ("-mega-z", "Mega Z")) if mega_api_name.endswith(suffix)), "Mega"),
            types=[t["type"]["name"] for t in data.get("types", [])],
            sprite_url=data.get("sprites", {}).get("front_default"),
            hp=stats.get("hp", 0),
            attack=stats.get("attack", 0),
            defense=stats.get("defense", 0),
            special_attack=stats.get("special-attack", 0),
            special_defense=stats.get("special-defense", 0),
            speed=stats.get("speed", 0),
            abilities=[format_display_name(a["ability"]["name"]) for a in data.get("abilities", []) if a.get("ability")],
            ability=ability,
        )
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Network error fetching Mega details for '{mega_api_name}': {e}")
        return None


