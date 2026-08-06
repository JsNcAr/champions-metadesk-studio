"""Service for syncing and managing the local Champions Pokédex species catalog."""

from sqlmodel import Session
from ..infrastructure.database.repositories import ChampionsCatalogRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import get_champions_pokedex_species


def sync_champions_catalog_on_startup(session: Session, pokedex_name: str = "champions") -> dict:
    """
    Queries PokéAPI for the specified Pokédex species roster (defaults to 'champions')
    and syncs any new additions into the local SQLite database.

    If offline or network fails, falls back to the existing database catalog gracefully.
    """
    repo = ChampionsCatalogRepository(session)
    remote_entries = get_champions_pokedex_species(pokedex_name=pokedex_name)

    if not remote_entries:
        existing_count = len(repo.list_all())
        print(f"ℹ️ Could not fetch remote {pokedex_name} Pokédex; using cached local DB catalog ({existing_count} species).")
        return {"status": "offline_cached", "added": 0, "total_local": existing_count}

    result = repo.sync_species_entries(remote_entries)
    added = result["added"]
    if added > 0:
        print(f"✅ Champions Pokédex catalog synced: Added {added} new species to local DB (Total: {result['total_remote']}).")
    else:
        print(f"✅ Champions Pokédex catalog up-to-date in local DB ({result['total_remote']} species).")

    return result
