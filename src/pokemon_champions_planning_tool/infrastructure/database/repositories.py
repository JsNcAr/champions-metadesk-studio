"""Simple SQLModel repositories for the local SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlmodel import Session, select

from ...domain.entities.box_entry import BoxEntry
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.team import Team
from ...domain.entities.team_member import TeamMember
from .models import BoxEntryRecord, PokemonRecord, TeamMemberRecord, TeamRecord


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

        existing_record.notes = new_record.notes
        existing_record.tags = new_record.tags
        existing_record.is_favorite = new_record.is_favorite
        existing_record.updated_at = _utc_now()
        self.session.add(existing_record)
        self.session.commit()
        self.session.refresh(existing_record)
        return existing_record

    def get_by_canonical_id(self, canonical_id: str) -> BoxEntryRecord | None:
        return self.session.exec(
            select(BoxEntryRecord).where(BoxEntryRecord.pokemon_canonical_id == canonical_id)
        ).first()

    def list_all(self) -> list[BoxEntryRecord]:
        return list(self.session.exec(select(BoxEntryRecord).order_by(BoxEntryRecord.created_at))) # type: ignore

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

    def get(self, team_id: UUID) -> TeamRecord | None:
        return self.session.get(TeamRecord, team_id)

    def list_all(self) -> list[TeamRecord]:
        return list(self.session.exec(select(TeamRecord).order_by(TeamRecord.name)))

    def delete(self, team_id: UUID) -> bool:
        record = self.get(team_id)
        if record is None:
            return False

        self.session.delete(record)
        self.session.commit()
        return True

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

    def list_members(self, team_id: UUID) -> list[TeamMemberRecord]:
        return list(
            self.session.exec(
                select(TeamMemberRecord)
                .where(TeamMemberRecord.team_id == team_id)
                .order_by(TeamMemberRecord.slot_position) # type: ignore
            )
        )