"""Simple SQLModel repositories for the local SQLite database."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func
from sqlmodel import func, Session, select

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
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
    TournamentSeedMetaRecord,
)
import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any



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
    """CRUD helpers for the user's box entries.

    Uniqueness rule (enforced here, not at DB level):
    - At most ONE non-planned entry per ``pokemon_canonical_id``.
    - Planned (ghost) entries are not subject to this constraint.
    """

    def __init__(self, session: Session):
        self.session = session
        self.pokemon_repository = PokemonRepository(session)

    def upsert_box_entry(self, box_entry: BoxEntry) -> BoxEntryRecord:
        self.pokemon_repository.upsert(box_entry.pokemon)
        # Enforce uniqueness only for real (non-planned) entries
        if not box_entry.is_planned:
            existing_record = self.session.exec(
                select(BoxEntryRecord).where(
                    BoxEntryRecord.pokemon_canonical_id == box_entry.pokemon.canonical_id,
                    BoxEntryRecord.is_planned == False,  # noqa: E712
                )
            ).first()
        else:
            existing_record = None

        new_record = BoxEntryRecord.from_domain(box_entry)

        if existing_record is None:
            self.session.add(new_record)
            self.session.commit()
            self.session.refresh(new_record)
            return new_record

        existing_record.pokemon_canonical_id = new_record.pokemon_canonical_id
        existing_record.notes = new_record.notes
        existing_record.tags = new_record.tags
        existing_record.is_favorite = new_record.is_favorite
        existing_record.is_planned = new_record.is_planned
        existing_record.updated_at = _utc_now()
        self.session.add(existing_record)
        self.session.commit()
        self.session.refresh(existing_record)
        return existing_record

    def create_planned_entry(self, box_entry: BoxEntry) -> BoxEntryRecord:
        """Insert a ghost/template entry (is_planned=True) without uniqueness checks."""
        self.pokemon_repository.upsert(box_entry.pokemon)
        record = BoxEntryRecord.from_domain(box_entry)
        record.is_planned = True
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def promote_planned_entry(self, box_entry_id: UUID) -> BoxEntryRecord | None:
        """Promote a ghost entry to a real box entry (is_planned -> False)."""
        record = self.session.get(BoxEntryRecord, box_entry_id)
        if record is None or not record.is_planned:
            return None
        record.is_planned = False
        record.updated_at = _utc_now()
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_by_canonical_id(self, canonical_id: str) -> BoxEntryRecord | None:
        """Returns the real (non-planned) entry for a canonical ID, if any."""
        return self.session.exec(
            select(BoxEntryRecord).where(
                BoxEntryRecord.pokemon_canonical_id == canonical_id,
                BoxEntryRecord.is_planned == False,  # noqa: E712
            )
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

    def list_all(self, include_planned: bool = False) -> list[BoxEntryRecord]:
        """Returns all real box entries sorted by creation date.

        Set ``include_planned=True`` to also return ghost/template entries.
        """
        stmt = select(BoxEntryRecord)
        if not include_planned:
            stmt = stmt.where(BoxEntryRecord.is_planned == False)  # noqa: E712
        records = list(self.session.exec(stmt))
        return sorted(records, key=lambda r: r.created_at)

    def load_entry(self, identifier: str) -> BoxEntry | None:
        record = self.resolve(identifier)
        if record is None:
            return None

        pokemon_record = self.pokemon_repository.get(record.pokemon_canonical_id)
        if pokemon_record is None:
            return None

        return record.to_domain(pokemon_record.to_domain())

    get = load_entry

    def list_entries(self, include_planned: bool = False) -> list[BoxEntry]:
        """Returns hydrated BoxEntry domain objects in creation order, in one query.

        ``include_planned=False`` (default) mirrors the main box grid behaviour —
        ghost entries are hidden unless explicitly requested.
        """
        stmt = select(BoxEntryRecord, PokemonRecord).join(
            PokemonRecord, BoxEntryRecord.pokemon_canonical_id == PokemonRecord.canonical_id
        )
        if not include_planned:
            stmt = stmt.where(BoxEntryRecord.is_planned == False)  # noqa: E712
        rows = sorted(self.session.exec(stmt).all(), key=lambda pair: pair[0].created_at)
        return [record.to_domain(pokemon.to_domain()) for record, pokemon in rows]

    def update_many(
        self,
        box_entry_ids: Iterable[UUID],
        *,
        add_tags: Iterable[str] = (),
        remove_tags: Iterable[str] = (),
        is_favorite: bool | None = None,
        is_planned: bool | None = None,
    ) -> int:
        """Apply the same metadata change to several entries in one commit."""
        ids = list(box_entry_ids)
        if not ids:
            return 0
        add = [t.strip() for t in add_tags if t and t.strip()]
        remove = {t.strip().lower() for t in remove_tags if t and t.strip()}
        records = self.session.exec(
            select(BoxEntryRecord).where(BoxEntryRecord.box_entry_id.in_(ids))
        ).all()
        for record in records:
            tags = [t for t in (record.tags or []) if t.lower() not in remove]
            for tag in add:
                if tag.lower() not in {t.lower() for t in tags}:
                    tags.append(tag)
            record.tags = tags
            if is_favorite is not None:
                record.is_favorite = is_favorite
            if is_planned is not None:
                record.is_planned = is_planned
            record.updated_at = _utc_now()
            self.session.add(record)
        self.session.commit()
        return len(records)

    def delete_many(self, box_entry_ids: Iterable[UUID]) -> int:
        """Delete entries and every team member referencing them, in one commit."""
        ids = list(box_entry_ids)
        if not ids:
            return 0
        members = self.session.exec(
            select(TeamMemberRecord).where(TeamMemberRecord.box_entry_id.in_(ids))
        ).all()
        for member in members:
            self.session.delete(member)
        records = self.session.exec(
            select(BoxEntryRecord).where(BoxEntryRecord.box_entry_id.in_(ids))
        ).all()
        for record in records:
            self.session.delete(record)
        self.session.commit()
        return len(records)

    def update_metadata(
        self,
        identifier: str,
        *,
        notes: str | None = None,
        tags: list[str] | None = None,
        is_favorite: bool | None = None,
        is_planned: bool | None = None,
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
        if is_planned is not None:
            record.is_planned = is_planned

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
        existing_record.selected_form = new_record.selected_form
        existing_record.item = new_record.item
        existing_record.moveset = new_record.moveset
        existing_record.ability = new_record.ability
        existing_record.notes = new_record.notes
        existing_record.evs = new_record.evs
        existing_record.ivs = new_record.ivs
        existing_record.nature = new_record.nature
        existing_record.level = new_record.level
        existing_record.tera_type = new_record.tera_type
        self.session.add(existing_record)
        self.session.commit()
        self.session.refresh(existing_record)
        return existing_record

    def _member_at(self, team_id: UUID, slot_position: int) -> TeamMemberRecord | None:
        return self.session.exec(
            select(TeamMemberRecord).where(
                TeamMemberRecord.team_id == team_id,
                TeamMemberRecord.slot_position == slot_position,
            )
        ).first()

    def swap_slots(self, team_id: UUID, slot_a: int, slot_b: int) -> bool:
        """Exchange the members of two slots in one transaction.

        A naive two-write swap violates ``uq_team_slot`` mid-way, so the first member
        is parked on a temporary negative slot until the other has moved. Swapping
        with an empty slot moves the member; two empty slots is a no-op. Returns
        whether anything changed.
        """
        if slot_a == slot_b:
            return False
        member_a = self._member_at(team_id, slot_a)
        member_b = self._member_at(team_id, slot_b)
        if member_a is None and member_b is None:
            return False

        if member_a is not None and member_b is not None:
            member_a.slot_position = -slot_a
            self.session.add(member_a)
            self.session.flush()
            member_b.slot_position = slot_a
            self.session.add(member_b)
            self.session.flush()
            member_a.slot_position = slot_b
            self.session.add(member_a)
        elif member_a is not None:
            member_a.slot_position = slot_b
            self.session.add(member_a)
        else:
            member_b.slot_position = slot_a
            self.session.add(member_b)
        self.session.commit()
        return True

    def move_member(self, team_id: UUID, from_slot: int, to_slot: int) -> bool:
        """Move a member to another slot, swapping if the target is occupied."""
        return self.swap_slots(team_id, from_slot, to_slot)

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

    def teams_containing(self, box_entry_id: UUID) -> list[tuple[str, int]]:
        """(team name, slot) for every team slot holding this box entry."""
        stmt = (
            select(TeamRecord.name, TeamMemberRecord.slot_position)
            .join(TeamMemberRecord, TeamMemberRecord.team_id == TeamRecord.team_id)
            .where(TeamMemberRecord.box_entry_id == box_entry_id)
            .order_by(TeamRecord.name, TeamMemberRecord.slot_position)
        )
        return [(name, slot) for name, slot in self.session.exec(stmt).all()]

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

    def get_members(self, team_id: UUID) -> list[TeamMember]:
        """Return hydrated domain TeamMember instances for a team."""
        return [record.to_domain() for record in self.list_members(team_id)]

    def load_team(self, team_id: UUID) -> Team | None:
        record = self.get(team_id)
        if record is None:
            return None

        members = self.get_members(team_id)
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


# ---------------------------------------------------------------------------
# TournamentRepository
# ---------------------------------------------------------------------------


class TournamentRepository:
    """Persistence operations for VGC Tournament metadata, teams, and seed datasets."""

    def __init__(self, session: Session):
        self.session = session

    def upsert_tournament(self, tournament: TournamentRecord) -> TournamentRecord:
        existing = self.session.get(TournamentRecord, tournament.tournament_id)
        if existing:
            existing.name = tournament.name
            existing.event_date = tournament.event_date
            existing.format_regulation = tournament.format_regulation
            existing.game_platform = tournament.game_platform
            existing.organizer = tournament.organizer
            existing.location = tournament.location
            existing.total_players = tournament.total_players
            existing.source_url = tournament.source_url
            # standings_synced is owned by the standings fetch, not by metadata
            # refreshes, so a re-listed tournament keeps its backlog state.
            existing.updated_at = _utc_now()
            self.session.add(existing)
            target = existing
        else:
            self.session.add(tournament)
            target = tournament
        self.session.commit()
        self.session.refresh(target)
        return target

    def get_tournament(self, tournament_id: str) -> TournamentRecord | None:
        return self.session.get(TournamentRecord, tournament_id)

    def mark_standings_synced(self, tournament_id: str, synced: bool = True) -> None:
        """Record whether a standings fetch for this tournament has succeeded."""
        record = self.session.get(TournamentRecord, tournament_id)
        if record is None:
            return
        record.standings_synced = synced
        record.updated_at = _utc_now()
        self.session.add(record)
        self.session.commit()

    def list_tournament_ids_pending_standings(self, source_prefix: str | None = None) -> set[str]:
        """Tournament IDs whose standings have never been fetched successfully."""
        stmt = select(TournamentRecord.tournament_id).where(
            TournamentRecord.standings_synced == False  # noqa: E712 - SQL boolean column
        )
        if source_prefix:
            stmt = stmt.where(TournamentRecord.tournament_id.startswith(source_prefix))
        return set(self.session.exec(stmt).all())

    def delete_teams_for_tournament(self, tournament_id: str) -> int:
        """Delete a tournament's teams and their members. Returns rows removed.

        Re-ingesting an event replaces its teams rather than appending to them, so a
        forced re-sync cannot duplicate rosters.
        """
        teams = list(
            self.session.exec(
                select(TournamentTeamRecord).where(
                    TournamentTeamRecord.tournament_id == tournament_id
                )
            ).all()
        )
        if not teams:
            return 0

        team_ids = [t.tournament_team_id for t in teams]
        members = self.session.exec(
            select(TournamentTeamMemberRecord).where(
                TournamentTeamMemberRecord.tournament_team_id.in_(team_ids)
            )
        ).all()
        for member in members:
            self.session.delete(member)
        for team in teams:
            self.session.delete(team)
        self.session.commit()
        return len(teams)

    def list_tournaments(self) -> list[TournamentRecord]:
        return list(self.session.exec(select(TournamentRecord).order_by(TournamentRecord.event_date.desc())).all())


    def save_team(
        self, team: TournamentTeamRecord, members: list[TournamentTeamMemberRecord]
    ) -> TournamentTeamRecord:
        self.session.add(team)
        self.session.commit()
        self.session.refresh(team)

        for m in members:
            m.tournament_team_id = team.tournament_team_id
            self.session.add(m)
        self.session.commit()
        return team

    def get_team(self, tournament_team_id: UUID) -> TournamentTeamRecord | None:
        return self.session.get(TournamentTeamRecord, tournament_team_id)

    def get_team_members(self, tournament_team_id: UUID) -> list[TournamentTeamMemberRecord]:
        stmt = (
            select(TournamentTeamMemberRecord)
            .where(TournamentTeamMemberRecord.tournament_team_id == tournament_team_id)
            .order_by(TournamentTeamMemberRecord.slot_position)
        )
        return list(self.session.exec(stmt).all())

    def list_teams_by_tournament(self, tournament_id: str) -> list[TournamentTeamRecord]:
        stmt = (
            select(TournamentTeamRecord)
            .where(TournamentTeamRecord.tournament_id == tournament_id)
            .order_by(TournamentTeamRecord.placement)
        )
        return list(self.session.exec(stmt).all())

    def _apply_search_filters(
        self,
        stmt,
        *,
        query: str | None,
        regulation_filter: str | None,
        placement_filter: int | None,
        species_filter: str | None,
        game_platform_filter: str | None,
        max_age_days: int | None,
    ):
        """Shared WHERE clauses for search_teams and count_teams."""

        if regulation_filter and regulation_filter != "All":
            stmt = stmt.where(TournamentRecord.format_regulation == regulation_filter)

        if game_platform_filter and game_platform_filter != "All":
            stmt = stmt.where(TournamentRecord.game_platform == game_platform_filter)

        if max_age_days is not None and max_age_days > 0:
            cutoff = _utc_now() - timedelta(days=max_age_days)
            stmt = stmt.where(TournamentRecord.event_date >= cutoff)

        if placement_filter:
            stmt = stmt.where(TournamentTeamRecord.placement <= placement_filter)

        if query:
            q_raw = query.strip()
            q_pattern = f"%{q_raw}%"
            q_canon = format_api_name(q_raw)
            c_pattern = f"%{q_canon}%" if q_canon else q_pattern

            subq_member = select(TournamentTeamMemberRecord.tournament_team_id).where(
                (TournamentTeamMemberRecord.species_name.ilike(q_pattern))
                | (TournamentTeamMemberRecord.canonical_id.ilike(q_pattern))
                | (TournamentTeamMemberRecord.canonical_id.ilike(c_pattern))
            )
            stmt = stmt.where(
                (TournamentTeamRecord.player_name.ilike(q_pattern))
                | (TournamentRecord.name.ilike(q_pattern))
                | (TournamentTeamRecord.tournament_id.ilike(q_pattern))
                | (TournamentTeamRecord.tournament_team_id.in_(subq_member))
            )

        if species_filter:
            s_pattern = f"%{species_filter.strip()}%"
            subq_spec = select(TournamentTeamMemberRecord.tournament_team_id).where(
                (TournamentTeamMemberRecord.species_name.ilike(s_pattern))
                | (TournamentTeamMemberRecord.canonical_id.ilike(s_pattern))
            )
            stmt = stmt.where(TournamentTeamRecord.tournament_team_id.in_(subq_spec))

        return stmt

    def _joined_teams(self):
        # Always join the tournament: recency is part of the ordering, so the join is
        # needed on every query anyway and the conditional-join bookkeeping only
        # invited bugs.
        return select(TournamentTeamRecord).join(
            TournamentRecord,
            TournamentTeamRecord.tournament_id == TournamentRecord.tournament_id,
        )

    def search_teams(
        self,
        query: str | None = None,
        regulation_filter: str | None = None,
        placement_filter: int | None = None,
        species_filter: str | None = None,
        game_platform_filter: str | None = None,
        max_age_days: int | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[TournamentTeamRecord]:
        stmt = self._apply_search_filters(
            self._joined_teams(),
            query=query,
            regulation_filter=regulation_filter,
            placement_filter=placement_filter,
            species_filter=species_filter,
            game_platform_filter=game_platform_filter,
            max_age_days=max_age_days,
        )

        # Newest event first, then best placement within that event. Ordering by
        # placement alone made a capped result set show only the top few finishes of
        # every event ever recorded, so recent tournaments could never surface.
        #
        # The team ID is a tiebreaker rather than decoration: bracket ties put several
        # teams on the same placement in the same event, and without a total order the
        # database may return equal rows in a different sequence per query, which makes
        # LIMIT/OFFSET paging skip and repeat rows.
        stmt = stmt.order_by(
            TournamentRecord.event_date.desc(),
            TournamentTeamRecord.placement.asc(),
            TournamentTeamRecord.tournament_team_id.asc(),
        )
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)

        return list(self.session.exec(stmt).all())

    def count_teams(
        self,
        query: str | None = None,
        regulation_filter: str | None = None,
        placement_filter: int | None = None,
        species_filter: str | None = None,
        game_platform_filter: str | None = None,
        max_age_days: int | None = None,
    ) -> int:
        """Number of teams matching the same filters as search_teams."""
        stmt = self._apply_search_filters(
            self._joined_teams(),
            query=query,
            regulation_filter=regulation_filter,
            placement_filter=placement_filter,
            species_filter=species_filter,
            game_platform_filter=game_platform_filter,
            max_age_days=max_age_days,
        )
        return int(self.session.exec(select(func.count()).select_from(stmt.subquery())).one() or 0)

    def list_regulations(self) -> list[str]:
        """Distinct regulation labels present in the data, most common first."""
        stmt = (
            select(TournamentRecord.format_regulation, func.count())
            .group_by(TournamentRecord.format_regulation)
            .order_by(func.count().desc())
        )
        return [reg for reg, _n in self.session.exec(stmt).all() if reg]

    def is_seeded(self, seed_version: str) -> bool:
        meta = self.session.get(TournamentSeedMetaRecord, 1)
        return meta is not None and meta.seed_version == seed_version

    def seed_from_file(self, json_file_path: Path, force: bool = False) -> dict[str, Any]:
        if not json_file_path.exists():
            return {"status": "file_not_found", "teams_added": 0}

        try:
            with open(json_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as err:
            return {"status": "read_error", "error": str(err), "teams_added": 0}

        version = data.get("seed_version", "seed_v1")
        if not force and self.is_seeded(version):
            return {"status": "skipped", "reason": "already_seeded", "teams_added": 0}

        tournaments_data = data.get("tournaments", [])
        total_tourneys = 0
        total_teams = 0

        for t_dict in tournaments_data:
            dt_str = t_dict.get("event_date")
            parsed_dt = _utc_now()
            if dt_str:
                try:
                    parsed_dt = datetime.fromisoformat(dt_str)
                except ValueError:
                    pass

            t_rec = TournamentRecord(
                tournament_id=t_dict["tournament_id"],
                name=t_dict["name"],
                event_date=parsed_dt,
                format_regulation=t_dict.get("format_regulation", "VGC"),
                game_platform=t_dict.get("game_platform", "Scarlet & Violet"),
                organizer=t_dict.get("organizer", "Official VGC"),
                location=t_dict.get("location", "Online"),
                total_players=t_dict.get("total_players", 0),
            )
            self.upsert_tournament(t_rec)
            total_tourneys += 1

            teams_data = t_dict.get("teams", [])
            for team_dict in teams_data:
                team_rec = TournamentTeamRecord(
                    tournament_id=t_rec.tournament_id,
                    player_name=team_dict["player_name"],
                    placement=team_dict["placement"],
                    standing_label=team_dict.get("standing_label", f"{team_dict['placement']}th Place"),
                    pokepast_url=team_dict.get("pokepast_url"),
                    showdown_text=team_dict.get("showdown_text", ""),
                    source_dataset=version,
                )
                members = []
                for idx, mem in enumerate(team_dict.get("members", []), start=1):
                    members.append(
                        TournamentTeamMemberRecord(
                            slot_position=idx,
                            canonical_id=mem["canonical_id"],
                            species_name=mem["species_name"],
                        )
                    )
                self.save_team(team_rec, members)
                total_teams += 1

        meta = self.session.get(TournamentSeedMetaRecord, 1)
        if meta is None:
            meta = TournamentSeedMetaRecord(
                id=1,
                seed_version=version,
                total_tournaments=total_tourneys,
                total_teams=total_teams,
            )
            self.session.add(meta)
        else:
            meta.seed_version = version
            meta.total_tournaments = total_tourneys
            meta.total_teams = total_teams
            meta.loaded_at = _utc_now()
            self.session.add(meta)
        self.session.commit()

        return {"status": "success", "tournaments_added": total_tourneys, "teams_added": total_teams}