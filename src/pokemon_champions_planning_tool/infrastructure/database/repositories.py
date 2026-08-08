"""Simple SQLModel repositories for the local SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select

from ...domain.entities.box_entry import BoxEntry
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.pokemon_move import PokemonMove
from ...domain.entities.team import Team
from ...domain.entities.team_member import TeamMember
from ...domain.pokemon_identity import format_api_name
from .models import (
    BoxEntryRecord,
    ChampionsSpeciesRecord,
    ItemCatalogMetaRecord,
    ItemRecord,
    MegaCheckedSpeciesRecord,
    MegaEvolutionRecord,
    PokemonRecord,
    TeamMemberRecord,
    TeamRecord,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PokemonRepository:
    """CRUD helpers for Pokemon records."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, pokemon: Pokemon) -> PokemonRecord:
        existing_record = self.session.get(PokemonRecord, pokemon.canonical_id)
        new_record = PokemonRecord.from_domain(pokemon)

        if existing_record is None:
            self.session.add(new_record)
            self.session.commit()
            self.session.refresh(new_record)
            return new_record

        for field_name in (
            "display_name",
            "species_name",
            "form_name",
            "dex_number",
            "types",
            "sprite_url",
            "hp",
            "attack",
            "defense",
            "special_attack",
            "special_defense",
            "speed",
            "abilities",
            "moves",
            "available_forms",
        ):
            setattr(existing_record, field_name, getattr(new_record, field_name))

        existing_record.updated_at = _utc_now()
        self.session.add(existing_record)
        self.session.commit()
        self.session.refresh(existing_record)
        return existing_record

    def get(self, canonical_id: str) -> PokemonRecord | None:
        return self.session.get(PokemonRecord, canonical_id)

    def list_all(self) -> list[PokemonRecord]:
        return list(self.session.exec(select(PokemonRecord).order_by(PokemonRecord.display_name)))


class BoxRepository:
    """CRUD helpers for the user's box entries."""

    def __init__(self, session: Session):
        self.session = session
        self.pokemon_repository = PokemonRepository(session)

    def upsert_box_entry(self, box_entry: BoxEntry) -> BoxEntryRecord:
        self.pokemon_repository.upsert(box_entry.pokemon)
        existing_record = self.session.exec(
            select(BoxEntryRecord).where(
                BoxEntryRecord.pokemon_canonical_id == box_entry.pokemon.canonical_id
            )
        ).first()
        new_record = BoxEntryRecord.from_domain(box_entry)

        if existing_record is None:
            self.session.add(new_record)
            self.session.commit()
            self.session.refresh(new_record)
            return new_record

        existing_record.pokemon_canonical_id = new_record.pokemon_canonical_id
        existing_record.updated_at = _utc_now()
        self.session.add(existing_record)
        self.session.commit()
        self.session.refresh(existing_record)
        return existing_record

    def get_by_canonical_id(self, canonical_id: str) -> BoxEntryRecord | None:
        return self.session.exec(
            select(BoxEntryRecord).where(BoxEntryRecord.pokemon_canonical_id == canonical_id)
        ).first()

    def resolve(self, identifier: str) -> BoxEntryRecord | None:
        normalized_identifier = identifier.strip()
        if not normalized_identifier:
            return None

        try:
            val_uuid = UUID(normalized_identifier)
            record = self.session.get(BoxEntryRecord, val_uuid)
            if record is not None:
                return record
        except ValueError:
            pass

        canonical_id = format_api_name(normalized_identifier) or normalized_identifier
        record = self.get_by_canonical_id(canonical_id)
        if record is not None:
            return record

        lowered_identifier = normalized_identifier.lower()
        for box_entry in self.list_all():
            pokemon_record = self.pokemon_repository.get(box_entry.pokemon_canonical_id)
            if pokemon_record is not None and pokemon_record.display_name.lower() == lowered_identifier:
                return box_entry

        return None

    def list_all(self) -> list[BoxEntryRecord]:
        records = list(self.session.exec(select(BoxEntryRecord)))
        return sorted(records, key=lambda record: record.created_at)

    def load_entry(self, identifier: str) -> BoxEntry | None:
        record = self.resolve(identifier)
        if record is None:
            return None

        pokemon_record = self.pokemon_repository.get(record.pokemon_canonical_id)
        if pokemon_record is None:
            return None

        return record.to_domain(pokemon_record.to_domain())

    get = load_entry

    def list_entries(self) -> list[BoxEntry]:
        entries: list[BoxEntry] = []
        for record in self.list_all():
            pokemon_record = self.pokemon_repository.get(record.pokemon_canonical_id)
            if pokemon_record is None:
                continue
            entries.append(record.to_domain(pokemon_record.to_domain()))
        return entries

    def update_metadata(
        self,
        identifier: str,
        *,
        notes: str | None = None,
        tags: list[str] | None = None,
        is_favorite: bool | None = None,
    ) -> BoxEntryRecord | None:
        record = self.resolve(identifier)
        if record is None:
            return None

        if notes is not None:
            record.notes = notes
        if tags is not None:
            record.tags = tags
        if is_favorite is not None:
            record.is_favorite = is_favorite

        record.updated_at = _utc_now()
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def delete_by_canonical_id(self, canonical_id: str) -> bool:
        record = self.get_by_canonical_id(canonical_id)
        if record is None:
            return False

        self.session.delete(record)
        self.session.commit()
        return True


class TeamRepository:
    """CRUD helpers for teams and team members."""

    def __init__(self, session: Session):
        self.session = session

    def create(self, team: Team) -> TeamRecord:
        record = TeamRecord.from_domain(team)
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_by_name(self, name: str) -> TeamRecord | None:
        normalized_name = name.strip().lower()
        if not normalized_name:
            return None

        return self.session.exec(
            select(TeamRecord).where(func.lower(TeamRecord.name) == normalized_name)
        ).first()

    def resolve(self, identifier: str) -> TeamRecord | None:
        normalized_identifier = identifier.strip()
        if not normalized_identifier:
            return None

        try:
            team_id = UUID(normalized_identifier)
        except ValueError:
            team_id = None

        if team_id is not None:
            record = self.get(team_id)
            if record is not None:
                return record

        return self.get_by_name(normalized_identifier)

    def get(self, team_id: UUID) -> TeamRecord | None:
        return self.session.get(TeamRecord, team_id)

    def list_all(self) -> list[TeamRecord]:
        records = list(self.session.exec(select(TeamRecord)))
        return sorted(records, key=lambda record: record.name.lower())

    def delete(self, team_id: UUID) -> bool:
        record = self.get(team_id)
        if record is None:
            return False

        self.session.delete(record)
        self.session.commit()
        return True

    def rename(self, team_id: UUID, new_name: str) -> TeamRecord | None:
        record = self.get(team_id)
        if record is None:
            return None

        record.name = new_name
        record.updated_at = _utc_now()
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def upsert_member(self, team_id: UUID, member: TeamMember) -> TeamMemberRecord:
        existing_record = self.session.exec(
            select(TeamMemberRecord).where(
                TeamMemberRecord.team_id == team_id,
                TeamMemberRecord.slot_position == member.slot_position,
            )
        ).first()
        new_record = TeamMemberRecord.from_domain(team_id, member)

        if existing_record is None:
            self.session.add(new_record)
            self.session.commit()
            self.session.refresh(new_record)
            return new_record

        existing_record.box_entry_id = new_record.box_entry_id
        existing_record.item = new_record.item
        existing_record.moveset = new_record.moveset
        existing_record.ability = new_record.ability
        existing_record.notes = new_record.notes
        self.session.add(existing_record)
        self.session.commit()
        self.session.refresh(existing_record)
        return existing_record

    def delete_member(self, team_id: UUID, slot_position: int) -> bool:
        record = self.session.exec(
            select(TeamMemberRecord).where(
                TeamMemberRecord.team_id == team_id,
                TeamMemberRecord.slot_position == slot_position,
            )
        ).first()
        if record is None:
            return False

        self.session.delete(record)
        self.session.commit()
        return True

    def delete_members_by_box_entry_id(self, box_entry_id: UUID) -> int:
        records = list(
            self.session.exec(
                select(TeamMemberRecord).where(TeamMemberRecord.box_entry_id == box_entry_id)
            )
        )
        for record in records:
            self.session.delete(record)
        if records:
            self.session.commit()
        return len(records)

    def list_members(self, team_id: UUID) -> list[TeamMemberRecord]:
        records = list(self.session.exec(select(TeamMemberRecord).where(TeamMemberRecord.team_id == team_id)))
        return sorted(records, key=lambda record: record.slot_position)

    def load_team(self, team_id: UUID) -> Team | None:
        record = self.get(team_id)
        if record is None:
            return None

        members = [member.to_domain() for member in self.list_members(team_id)]
        return record.to_domain(members)


class ChampionsCatalogRepository:
    """Repository for managing the Champions Pokédex species catalog."""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[ChampionsSpeciesRecord]:
        records = list(self.session.exec(select(ChampionsSpeciesRecord)))
        for r in records:
            self.session.expunge(r)
        return sorted(records, key=lambda r: r.entry_number)

    def list_species_names(self) -> list[str]:
        return [r.species_name for r in self.list_all()]

    def sync_species_entries(self, entries: list[dict[str, Any]]) -> dict[str, Any]:
        """Saves any species entries from PokéAPI that are missing from the local catalog."""
        existing_names = set(self.list_species_names())
        added_count = 0

        for entry in entries:
            name = entry["species_name"]
            if name not in existing_names:
                record = ChampionsSpeciesRecord(
                    entry_number=entry["entry_number"],
                    species_name=name,
                    display_name=entry.get("display_name", name.title()),
                )
                self.session.add(record)
                added_count += 1

        if added_count > 0:
            self.session.commit()

        return {
            "total_remote": len(entries),
            "added": added_count,
            "existing": len(existing_names),
        }


class MegaEvolutionRepository:
    """Repository for managing Mega Evolution records in SQLite."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, canonical_id: str) -> MegaEvolutionRecord | None:
        rec = self.session.get(MegaEvolutionRecord, canonical_id)
        if rec is not None:
            self.session.expunge(rec)
        return rec

    def list_by_species(self, species_name: str) -> list[MegaEvolutionRecord]:
        records = list(
            self.session.exec(
                select(MegaEvolutionRecord).where(
                    func.lower(MegaEvolutionRecord.species_name) == species_name.strip().lower()
                )
            )
        )
        for r in records:
            self.session.expunge(r)
        return sorted(records, key=lambda r: r.canonical_id)

    def list_all(self) -> list[MegaEvolutionRecord]:
        records = list(self.session.exec(select(MegaEvolutionRecord)))
        for r in records:
            self.session.expunge(r)
        return sorted(records, key=lambda r: r.canonical_id)

    def is_species_checked(self, species_name: str) -> bool:
        normalized = species_name.strip().lower()
        return self.session.get(MegaCheckedSpeciesRecord, normalized) is not None

    def mark_species_checked(self, species_name: str) -> None:
        normalized = species_name.strip().lower()
        if not self.is_species_checked(normalized):
            record = MegaCheckedSpeciesRecord(species_name=normalized)
            self.session.add(record)
            self.session.commit()

    def upsert(self, record: MegaEvolutionRecord) -> MegaEvolutionRecord:
        existing = self.get(record.canonical_id)
        if existing is None:
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            return record

        existing.species_name = record.species_name
        existing.display_name = record.display_name
        existing.form_name = record.form_name
        existing.types = record.types
        existing.sprite_url = record.sprite_url
        existing.hp = record.hp
        existing.attack = record.attack
        existing.defense = record.defense
        existing.special_attack = record.special_attack
        existing.special_defense = record.special_defense
        existing.speed = record.speed
        self.session.add(existing)
        self.session.commit()
        self.session.refresh(existing)
        return existing


class ItemRepository:
    """CRUD helpers for item catalog records and sync metadata."""

    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------
    # Item CRUD
    # ------------------------------------------------------------------

    def get(self, canonical_id: str) -> ItemRecord | None:
        rec = self.session.get(ItemRecord, canonical_id)
        if rec is not None:
            self.session.expunge(rec)
        return rec

    def upsert(self, record: ItemRecord) -> ItemRecord:
        """Insert or update an item record. Returns the persisted record."""
        existing = self.session.get(ItemRecord, record.canonical_id)
        if existing is None:
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            self.session.expunge(record)
            return record

        # Update mutable fields
        existing.display_name = record.display_name
        existing.category = record.category
        existing.is_champions_legal = record.is_champions_legal
        existing.sprite_url = record.sprite_url
        existing.short_effect = record.short_effect
        existing.target_species = record.target_species
        existing.target_form = record.target_form
        existing.stat_modifiers = record.stat_modifiers
        existing.updated_at = _utc_now()
        self.session.add(existing)
        self.session.commit()
        self.session.refresh(existing)
        self.session.expunge(existing)
        return existing

    def delete(self, canonical_id: str) -> None:
        """Deletes an item record by canonical_id."""
        rec = self.session.get(ItemRecord, canonical_id)
        if rec is not None:
            self.session.delete(rec)
            self.session.commit()

    def list_all(self) -> list[ItemRecord]:
        records = list(self.session.exec(select(ItemRecord)))
        for r in records:
            self.session.expunge(r)
        return sorted(records, key=lambda r: r.canonical_id)

    def list_champions_legal(self) -> list[ItemRecord]:
        """Returns only items flagged as legal in the Champions format."""
        records = list(
            self.session.exec(
                select(ItemRecord).where(ItemRecord.is_champions_legal == True)  # noqa: E712
            )
        )
        for r in records:
            self.session.expunge(r)
        return sorted(records, key=lambda r: r.canonical_id)

    def list_mega_stones(self) -> list[ItemRecord]:
        """Returns all Mega Stone items (those with a target_species set)."""
        records = list(
            self.session.exec(
                select(ItemRecord).where(ItemRecord.target_species != None)  # noqa: E711
            )
        )
        for r in records:
            self.session.expunge(r)
        return sorted(records, key=lambda r: r.canonical_id)

    def count(self) -> int:
        return len(self.session.exec(select(ItemRecord)).all())

    # ------------------------------------------------------------------
    # Staleness sentinel (ItemCatalogMetaRecord singleton)
    # ------------------------------------------------------------------

    def get_meta(self) -> ItemCatalogMetaRecord | None:
        return self.session.get(ItemCatalogMetaRecord, 1)

    def update_meta(self, total_holdable_items: int) -> None:
        """Upsert the singleton meta row with the current known item count."""
        meta = self.session.get(ItemCatalogMetaRecord, 1)
        if meta is None:
            meta = ItemCatalogMetaRecord(
                id=1, total_holdable_items=total_holdable_items
            )
            self.session.add(meta)
        else:
            meta.total_holdable_items = total_holdable_items
            meta.last_synced_at = _utc_now()
            self.session.add(meta)
        self.session.commit()