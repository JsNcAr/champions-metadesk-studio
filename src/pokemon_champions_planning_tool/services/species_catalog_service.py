"""Species catalogue sync and loading: Showdown's pokedex (with Champions legality) into SQLite."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from ..config import MOVE_CATALOG_MAX_AGE_DAYS, SPECIES_CATALOG_SCHEMA_VERSION
from ..domain.species import SpeciesInfo
from ..infrastructure.database.models import SpeciesRecord
from ..infrastructure.database.repositories import SpeciesRepository
from ..infrastructure.providers.showdown_species_provider import ShowdownSpeciesNetworkError, ShowdownSpeciesProvider


def species_catalog_is_stale(session: Session, max_age_days: int = MOVE_CATALOG_MAX_AGE_DAYS) -> bool:
    meta = SpeciesRepository(session).get_meta()
    if meta is None or meta.species_count == 0:
        return True
    if meta.schema_version is None or meta.schema_version < SPECIES_CATALOG_SCHEMA_VERSION:
        return True
    synced = meta.last_synced_at
    if synced.tzinfo is None:
        synced = synced.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - synced > timedelta(days=max_age_days)


def sync_species_catalog(session: Session, force: bool = False, provider: ShowdownSpeciesProvider | None = None) -> dict:
    """Fetch Showdown's pokedex and Champions legality, replacing the local catalogue.

    Returns {"status": "synced"|"cached"|"offline", "species": N, "legal": M}.
    """
    repo = SpeciesRepository(session)
    if not force and not species_catalog_is_stale(session):
        meta = repo.get_meta()
        return {"status": "cached", "species": meta.species_count, "legal": meta.legal_count}
    try:
        payload = (provider or ShowdownSpeciesProvider()).fetch_species_catalog()
    except ShowdownSpeciesNetworkError as exc:
        print(f"⚠️ Species catalogue: {exc}. Keeping the local data.")
        meta = repo.get_meta()
        return {"status": "offline", "species": meta.species_count if meta else 0, "legal": meta.legal_count if meta else 0}
    records = [
        SpeciesRecord(
            showdown_id=s.showdown_id, canonical_id=s.canonical_id, name=s.name, dex_number=s.dex_number, base_species_id=s.base_species_id,
            forme=s.forme, types=list(s.types), hp=s.base_stats["hp"], attack=s.base_stats["atk"], defense=s.base_stats["def"],
            special_attack=s.base_stats["spa"], special_defense=s.base_stats["spd"], speed=s.base_stats["spe"], abilities=list(s.abilities),
            hidden_ability=s.hidden_ability, weightkg=s.weightkg, gender=s.gender, required_item=s.required_item, battle_only=s.battle_only,
            is_mega=s.is_mega, is_legal=s.is_legal,
        )
        for s in payload.species
    ]
    count, legal = repo.replace_all(records)
    print(f"✅ Species catalogue synced: {count} species, {legal} legal in Champions.")
    return {"status": "synced", "species": count, "legal": legal}


def sync_species_catalog_on_startup(session: Session) -> dict:
    """Startup hook: never raises; syncs only when missing, older than the max age or reshaped."""
    try:
        return sync_species_catalog(session, force=False)
    except Exception as exc:  # noqa: BLE001 - startup must not depend on the network
        print(f"⚠️ Species catalogue check skipped: {exc}")
        return {"status": "error", "species": 0, "legal": 0}


def _to_info(r: SpeciesRecord) -> SpeciesInfo:
    return SpeciesInfo(
        canonical_id=r.canonical_id, showdown_id=r.showdown_id, name=r.name, dex_number=r.dex_number, base_species_id=r.base_species_id,
        forme=r.forme, types=tuple(r.types or ()), base_stats={"hp": r.hp, "atk": r.attack, "def": r.defense, "spa": r.special_attack, "spd": r.special_defense, "spe": r.speed},
        abilities=tuple(r.abilities or ()), weightkg=float(r.weightkg), gender=r.gender, required_item=r.required_item, battle_only=r.battle_only,
        is_mega=bool(r.is_mega), is_legal=bool(r.is_legal),
    )


def load_species_catalog(session: Session) -> dict[str, SpeciesInfo]:
    """Species by our canonical id (immutable values for the UI catalogs)."""
    import json

    def _decode(value) -> tuple:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return ()
        return tuple(value or ())

    out: dict[str, SpeciesInfo] = {}
    for row in SpeciesRepository(session).rows():
        (showdown_id, canonical_id, name, dex_number, base_species_id, forme, types,
         hp, attack, defense, special_attack, special_defense, speed, abilities,
         hidden_ability, weightkg, gender, required_item, battle_only, is_mega, is_legal) = row
        out[canonical_id] = SpeciesInfo(
            canonical_id=canonical_id, showdown_id=showdown_id, name=name, dex_number=dex_number,
            base_species_id=base_species_id, forme=forme, types=_decode(types),
            base_stats={"hp": hp, "atk": attack, "def": defense, "spa": special_attack, "spd": special_defense, "spe": speed},
            abilities=_decode(abilities), weightkg=float(weightkg), gender=gender,
            required_item=required_item, battle_only=battle_only,
            is_mega=bool(is_mega), is_legal=bool(is_legal),
        )
    return out


__all__ = ["load_species_catalog", "species_catalog_is_stale", "sync_species_catalog", "sync_species_catalog_on_startup"]
