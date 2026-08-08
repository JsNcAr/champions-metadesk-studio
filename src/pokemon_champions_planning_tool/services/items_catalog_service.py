"""Service for syncing and caching the held item catalog in SQLite.

Startup flow (normal run — DB already populated):
  1. Call check_items_catalog_staleness() → reads local DB meta, compares
     total_holdable_items against Showdown's current count. Cost: ~150ms
     (one cached Showdown HTTP call). Returns True if re-sync is needed.
  2. If stale or force=True, call sync_items_catalog() which:
       a. Fetches Showdown legal slugs + Mega Stone mappings (1 HTTP call, cached).
       b. Diffs against existing DB canonical_ids.
       c. Fetches PokéAPI detail ONLY for new items.
       d. Upserts all records and updates ItemCatalogMetaRecord.
  3. Call load_items_catalog() once to prime application state dicts.

All UI code reads from state dicts — zero DB queries during rendering.
"""

from __future__ import annotations

from sqlmodel import Session

from ..database.models import ItemRecord
from ..database.repositories import ItemRepository
from ..providers import HybridItemProvider


def check_items_catalog_staleness(session: Session) -> bool:
    """Returns True if the Showdown item count differs from the local DB count.

    Cost: one cached Showdown HTTP call (~150ms first time, 0ms thereafter).
    """
    repo = ItemRepository(session)
    meta = repo.get_meta()
    local_count = meta.total_holdable_items if meta else 0

    provider = HybridItemProvider()
    remote_count = provider.get_champions_legal_count()

    if remote_count == 0:
        # Showdown unreachable — treat as not stale so we don't block startup
        print("ℹ️ Items: Showdown unreachable; skipping staleness check.")
        return False

    is_stale = remote_count != local_count
    if is_stale:
        print(
            f"🔄 Items: Showdown reports {remote_count} legal items, "
            f"local DB has {local_count}. Re-sync needed."
        )
    return is_stale


def sync_items_catalog(session: Session, force: bool = False) -> dict:
    """Syncs the item catalog from Showdown + PokéAPI into SQLite.

    Args:
        session: Active SQLModel session.
        force: If True, re-fetches all items regardless of staleness.

    Returns:
        {"status": "synced"|"cached"|"offline", "added": N, "updated": M, "total": T}
    """
    repo = ItemRepository(session)

    # Fast path: already synced and not forced
    if not force and not check_items_catalog_staleness(session):
        total = repo.count()
        if total > 0:
            print(f"✅ Items catalog up-to-date in local DB ({total} items).")
            return {"status": "cached", "added": 0, "updated": 0, "total": total}

    provider = HybridItemProvider()

    # Collect existing canonical_ids to avoid redundant PokéAPI fetches
    existing = {r.canonical_id for r in repo.list_all()}

    # If forced, clear Showdown cache so we re-fetch from GitHub
    if force:
        provider.clear_cache()

    new_records = provider.fetch_item_records(existing_pokeapi_slugs=existing)

    if not new_records:
        print("⚠️ Items: No item data retrieved (offline?). Using cached DB.")
        return {"status": "offline", "added": 0, "updated": 0, "total": repo.count()}

    added = 0
    updated = 0
    for record in new_records:
        was_new = repo.get(record.canonical_id) is None
        repo.upsert(record)
        if was_new:
            added += 1
        else:
            updated += 1

    # Update the staleness sentinel
    legal_count = provider.get_champions_legal_count()
    repo.update_meta(total_holdable_items=legal_count)

    total = repo.count()
    print(
        f"✅ Items catalog synced: {added} added, {updated} updated "
        f"(Total: {total} items)."
    )
    return {"status": "synced", "added": added, "updated": updated, "total": total}


def load_items_catalog(session: Session, state: dict) -> None:
    """Primes application state dicts from the local SQLite item catalog.

    Populates:
        state["items_catalog"]     -> list[ItemRecord]  (all items)
        state["items_by_id"]       -> dict[canonical_id, ItemRecord]
        state["mega_stone_map"]    -> dict[species_name, list[ItemRecord]]
        state["champions_items"]   -> list[ItemRecord]  (legal-only filtered)

    Call this once at startup after sync_items_catalog() completes.
    """
    repo = ItemRepository(session)
    all_items = repo.list_all()

    state["items_catalog"] = all_items
    state["items_by_id"] = {item.canonical_id: item for item in all_items}
    state["champions_items"] = [i for i in all_items if i.is_champions_legal]

    mega_stone_map: dict[str, list[ItemRecord]] = {}
    for item in all_items:
        if item.target_species:
            mega_stone_map.setdefault(item.target_species, []).append(item)
    state["mega_stone_map"] = mega_stone_map

    legal_count = len(state["champions_items"])
    mega_count = sum(len(v) for v in mega_stone_map.values())
    print(
        f"✅ Items catalog loaded into state: {legal_count} Champions-legal items, "
        f"{mega_count} Mega Stone entries."
    )
