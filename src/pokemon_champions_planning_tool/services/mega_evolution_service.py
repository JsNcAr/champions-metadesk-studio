"""Service for discovering, syncing, and caching Mega Evolutions in SQLite."""

from sqlmodel import Session
from ..infrastructure.database.repositories import ChampionsCatalogRepository, MegaEvolutionRepository
from ..infrastructure.pokeapi.pokeapi_retrieval import get_mega_varieties_for_species, get_official_mega_details


def sync_mega_evolutions_for_species(session: Session, species_name: str) -> list:
    """
    Checks local SQLite for Mega Evolutions of a given species.
    If species was already checked against PokéAPI, returns cached megas immediately (0ms).
    Otherwise, fetches variety names from PokéAPI and records species as checked in SQLite.
    """
    mega_repo = MegaEvolutionRepository(session)
    normalized_species = species_name.strip().lower()

    # Fast path: If species was already checked, return cached megas without network calls
    if mega_repo.is_species_checked(normalized_species):
        return mega_repo.list_by_species(normalized_species)

    # Fetch variety names from PokéAPI
    mega_canonical_ids = get_mega_varieties_for_species(normalized_species)
    fetched_megas = []

    for canonical_id in mega_canonical_ids:
        mega_record = mega_repo.get(canonical_id)
        if not mega_record:
            mega_record = get_official_mega_details(canonical_id)
            if mega_record:
                mega_repo.upsert(mega_record)

        if mega_record:
            fetched_megas.append(mega_record)

    # Mark species as checked so future drawer openings hit DB cache only
    mega_repo.mark_species_checked(normalized_species)
    return fetched_megas


def sync_all_champions_megas_on_startup(session: Session) -> dict:
    """
    Scans all Champions catalog species for Mega Evolutions, upserting any missing Mega records into SQLite.
    Only queries PokéAPI for species that have not yet been checked.
    Handles network offline states gracefully by preserving cached database records.
    """
    catalog_repo = ChampionsCatalogRepository(session)
    mega_repo = MegaEvolutionRepository(session)

    species_list = catalog_repo.list_species_names()
    added_count = 0

    for species_name in species_list:
        if not mega_repo.is_species_checked(species_name):
            megas = sync_mega_evolutions_for_species(session, species_name)
            added_count += len(megas)

    total_now = len(mega_repo.list_all())
    if added_count > 0:
        print(f"✅ Mega Evolutions catalog synced: Added {added_count} Mega forms to local DB (Total: {total_now}).")
    else:
        print(f"✅ Mega Evolutions catalog up-to-date in local DB ({total_now} Mega forms).")

    return {
        "added": added_count,
        "total_local": total_now,
    }
