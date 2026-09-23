"""Simple SQLModel repositories for the local SQLite database."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import or_
from sqlmodel import Session, delete, func, select

from ...config import MOVE_CATALOG_SCHEMA_VERSION, SPECIES_CATALOG_SCHEMA_VERSION
from ...domain.entities.box_entry import BoxEntry
from ...domain.event_tier import classify_event_tier
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.team import Team
from ...domain.entities.team_member import TeamMember
from ...domain.pokemon_identity import expand_canonical_aliases, format_api_name
from ...domain.search import parse_search_query
from .models import (
    AppStateRecord,
    BoxEntryRecord,
    ChampionsSpeciesRecord,
    ItemCatalogMetaRecord,
    ItemRecord,
    LearnsetRecord,
    MegaCheckedSpeciesRecord,
    SpeciesCatalogMetaRecord,
    SpeciesRecord,
    MegaEvolutionRecord,
    MoveCatalogMetaRecord,
    MoveRecord,
    PokemonRecord,
    RivalTeamRecord,
    TeamMemberRecord,
    TeamRecord,
    TournamentRecord,
    TournamentSeedMetaRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
import json
from pathlib import Path
from collections.abc import Iterable
from typing import Any



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PlaceholderPokemonError(ValueError):
    """A Pokémon without PokéAPI data was about to be stored as if it were real."""


class PokemonRepository:
    """CRUD helpers for Pokemon records."""

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, pokemon: Pokemon) -> PokemonRecord:
        existing_record = self.session.get(PokemonRecord, pokemon.canonical_id)
        # A placeholder never overwrites real data: the worst that can happen is that
        # a stale placeholder is stored beside nothing, and the repair pass fixes that.
        if existing_record is not None and pokemon.is_stub and not existing_record.to_domain().is_stub:
            return existing_record
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
            "is_placeholder",
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

    def upsert_box_entry(self, box_entry: BoxEntry, *, allow_placeholder: bool = False) -> BoxEntryRecord:
        """Store an owned entry. A placeholder Pokémon is refused unless the caller says the
        gap is intentional (an import while PokéAPI is unreachable) — that is how a
        zero-stat "Pokémon" once ended up in the box unnoticed."""
        if box_entry.pokemon.is_stub and not allow_placeholder:
            raise PlaceholderPokemonError(f"{box_entry.pokemon.display_name} has no PokéAPI data; fetch it before storing it in the box")
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

    def create_planned_entry(self, box_entry: BoxEntry, *, allow_placeholder: bool = False) -> BoxEntryRecord:
        """Insert a ghost/template entry (is_planned=True) without uniqueness checks."""
        if box_entry.pokemon.is_stub and not allow_placeholder:
            raise PlaceholderPokemonError(f"{box_entry.pokemon.display_name} has no PokéAPI data; fetch it before storing it in the box")
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

    def list_entries_by_ids(self, box_entry_ids: Iterable[UUID]) -> dict[UUID, BoxEntry]:
        """Hydrate just these entries, keyed by id, in one query.

        A team has at most six slots; reading and validating the whole box to look them
        up cost the same whether the box held six Pokémon or six hundred. Planned entries
        are included — a slot may hold one.
        """
        ids = list(dict.fromkeys(box_entry_ids))
        if not ids:
            return {}
        stmt = (
            select(BoxEntryRecord, PokemonRecord)
            .join(PokemonRecord, BoxEntryRecord.pokemon_canonical_id == PokemonRecord.canonical_id)
            .where(BoxEntryRecord.box_entry_id.in_(ids))
        )
        return {
            record.box_entry_id: record.to_domain(pokemon.to_domain())
            for record, pokemon in self.session.exec(stmt).all()
        }

    def update_many(
        self,
        box_entry_ids: Iterable[UUID],
        *,
        add_tags: Iterable[str] = (),
        remove_tags: Iterable[str] = (),
        is_favorite: bool | None = None,
        is_planned: bool | None = None,
        notes: str | None = None,
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
            if notes is not None:
                record.notes = notes
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

    def set_format(self, team_id: UUID, format_id: str | None) -> TeamRecord | None:
        record = self.get(team_id)
        if record is None:
            return None
        record.format_id = format_id
        record.updated_at = _utc_now()
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

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
            self._touch(team_id)
            self.session.commit()
            self.session.refresh(new_record)
            return new_record

        existing_record.box_entry_id = new_record.box_entry_id
        existing_record.selected_form = new_record.selected_form
        existing_record.item = new_record.item
        existing_record.moveset = new_record.moveset
        existing_record.ability = new_record.ability
        existing_record.notes = new_record.notes
        existing_record.points = new_record.points
        existing_record.evs = new_record.evs
        existing_record.ivs = new_record.ivs
        existing_record.nature = new_record.nature
        existing_record.level = new_record.level
        existing_record.tera_type = new_record.tera_type
        self.session.add(existing_record)
        self._touch(team_id)
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
        self._touch(team_id)
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
        self._touch(team_id)
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

    def _touch(self, team_id: UUID) -> None:
        """Mark a team edited (the library sorts by it); committed with the caller's change."""
        record = self.get(team_id)
        if record is not None:
            record.updated_at = _utc_now()
            self.session.add(record)

    def list_with_species(self) -> list[tuple[TeamRecord, list[tuple[int, str, str | None, str | None]]]]:
        """Every team with its members as (slot, display name, canonical id, form), in one
        joined query: the team library draws six sprites per team without loading slots."""
        teams = self.list_all()
        stmt = (
            select(TeamMemberRecord.team_id, TeamMemberRecord.slot_position, PokemonRecord.display_name,
                   PokemonRecord.canonical_id, TeamMemberRecord.selected_form)
            .join(BoxEntryRecord, BoxEntryRecord.box_entry_id == TeamMemberRecord.box_entry_id)
            .join(PokemonRecord, PokemonRecord.canonical_id == BoxEntryRecord.pokemon_canonical_id)
        )
        members: dict[UUID, list[tuple[int, str, str | None, str | None]]] = {}
        for team_id, slot, name, canonical_id, form in self.session.exec(stmt).all():
            members.setdefault(team_id, []).append((int(slot), name, canonical_id, form))
        return [(t, sorted(members.get(t.team_id, []))) for t in teams]

    def member_counts(self) -> dict[UUID, int]:
        """{team id: filled slots} for every team in one grouped query.

        The team pickers ask for this whenever they are drawn — the Box redraws its
        "Add to team" menu on every card click — so it must not be a query per team.
        """
        stmt = select(TeamMemberRecord.team_id, func.count()).group_by(TeamMemberRecord.team_id)
        return {team_id: int(n or 0) for team_id, n in self.session.exec(stmt).all()}

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


class RivalTeamRepository:
    """Rival teams for the calculator: saved plans and the one "Current battle" team."""

    def __init__(self, session: Session):
        self.session = session

    def list_saved(self) -> list[RivalTeamRecord]:
        """Saved rival teams, most recently used first."""
        stmt = select(RivalTeamRecord).where(RivalTeamRecord.kind == "saved").order_by(RivalTeamRecord.last_used_at.desc())
        return list(self.session.exec(stmt).all())

    def get(self, rival_team_id: UUID) -> RivalTeamRecord | None:
        return self.session.get(RivalTeamRecord, rival_team_id)

    def battle(self) -> RivalTeamRecord | None:
        return self.session.exec(select(RivalTeamRecord).where(RivalTeamRecord.kind == "battle")).first()

    def upsert(self, record: RivalTeamRecord) -> RivalTeamRecord:
        """Insert or update; a new battle team replaces the previous one (there is only one)."""
        if record.kind == "battle":
            for old in self.session.exec(select(RivalTeamRecord).where(RivalTeamRecord.kind == "battle")).all():
                if old.rival_team_id != record.rival_team_id:
                    self.session.delete(old)
        record.updated_at = _utc_now()
        merged = self.session.merge(record)
        self.session.commit()
        self.session.refresh(merged)
        return merged

    def delete(self, rival_team_id: UUID) -> bool:
        record = self.session.get(RivalTeamRecord, rival_team_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.commit()
        return True


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
        """Catalogue species names in entry order — one column, no ORM objects.

        Every Meta page load asks for these to judge legality, so building and expunging
        two hundred records for the name alone was not worth it.
        """
        return [
            name
            for (name,) in self.session.connection().exec_driver_sql(
                "SELECT species_name FROM champions_species ORDER BY entry_number"
            )
        ]

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


class MoveRepository:
    """Move catalogue: moves, Champions learnsets and the sync sentinel."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def count_moves(self) -> int:
        return int(self.session.exec(select(func.count()).select_from(MoveRecord)).one() or 0)

    def count_learnsets(self) -> int:
        return int(self.session.exec(select(func.count()).select_from(LearnsetRecord)).one() or 0)

    def get_meta(self) -> MoveCatalogMetaRecord | None:
        return self.session.get(MoveCatalogMetaRecord, 1)

    # The catalogue readers below go through the driver cursor rather than the ORM: the
    # rows are turned into immutable value objects straight away and never written back,
    # so identity-mapping and expunging ~1 k moves and ~16 k learnset pairs at every
    # launch was pure overhead (roughly half the catalogue load time).

    MOVE_COLUMNS = (
        "move_id", "name", "type", "category", "power", "accuracy", "pp", "priority",
        "target", "short_desc", "is_legal", "mechanics",
    )

    def move_rows(self) -> list[tuple]:
        """Raw move rows in ``MOVE_COLUMNS`` order; ``mechanics`` is still JSON text."""
        return list(
            self.session.connection().exec_driver_sql(
                f"SELECT {', '.join(self.MOVE_COLUMNS)} FROM moves"
            )
        )

    def list_moves(self) -> list[MoveRecord]:
        records = list(self.session.exec(select(MoveRecord)).all())
        for r in records:
            self.session.expunge(r)
        return records

    def list_learnsets(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for species_key, move_id in self.session.connection().exec_driver_sql(
            "SELECT species_key, move_id FROM learnsets"
        ):
            out.setdefault(species_key, []).append(move_id)
        return out

    def replace_all(self, moves: list[MoveRecord], learnsets: dict[str, list[str]]) -> tuple[int, int]:
        """Swap the whole catalogue in one transaction (it is small: ~950 moves, ~16k pairs)."""
        self.session.exec(delete(LearnsetRecord))
        self.session.exec(delete(MoveRecord))
        for m in moves:
            self.session.add(m)
        pairs = 0
        for species_key, move_ids in learnsets.items():
            for move_id in dict.fromkeys(move_ids):
                self.session.add(LearnsetRecord(species_key=species_key, move_id=move_id))
                pairs += 1
        meta = self.get_meta() or MoveCatalogMetaRecord(id=1)
        meta.move_count = len(moves)
        meta.learnset_count = pairs
        meta.species_count = len(learnsets)
        meta.last_synced_at = _utc_now()
        meta.schema_version = MOVE_CATALOG_SCHEMA_VERSION
        self.session.add(meta)
        self.session.commit()
        return len(moves), pairs


class SpeciesRepository:
    """Species catalogue from Showdown's pokedex and the sync sentinel."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_meta(self) -> SpeciesCatalogMetaRecord | None:
        return self.session.get(SpeciesCatalogMetaRecord, 1)

    def count(self) -> int:
        return int(self.session.exec(select(func.count()).select_from(SpeciesRecord)).one() or 0)

    def get(self, showdown_id: str) -> SpeciesRecord | None:
        record = self.session.get(SpeciesRecord, showdown_id)
        if record is not None:
            self.session.expunge(record)
        return record

    def list_all(self) -> list[SpeciesRecord]:
        records = list(self.session.exec(select(SpeciesRecord)).all())
        for r in records:
            self.session.expunge(r)
        return records

    COLUMNS = (
        "showdown_id", "canonical_id", "name", "dex_number", "base_species_id", "forme",
        "types", "hp", "attack", "defense", "special_attack", "special_defense", "speed",
        "abilities", "hidden_ability", "weightkg", "gender", "required_item",
        "battle_only", "is_mega", "is_legal",
    )

    def rows(self) -> list[tuple]:
        """Raw catalogue rows in ``COLUMNS`` order; the JSON columns are still text.

        See the note on ``MoveRepository``: the UI catalogue turns these straight into
        frozen values, so the ORM round-trip only costs time at launch.
        """
        return list(
            self.session.connection().exec_driver_sql(
                f"SELECT {', '.join(self.COLUMNS)} FROM species_catalog"
            )
        )

    def replace_all(self, records: list[SpeciesRecord]) -> tuple[int, int]:
        """Swap the whole catalogue (~1.5k rows) in one transaction; returns (count, legal)."""
        self.session.exec(delete(SpeciesRecord))
        legal = 0
        for r in records:
            self.session.add(r)
            legal += 1 if r.is_legal else 0
        meta = self.get_meta() or SpeciesCatalogMetaRecord(id=1)
        meta.species_count = len(records)
        meta.legal_count = legal
        meta.last_synced_at = _utc_now()
        meta.schema_version = SPECIES_CATALOG_SCHEMA_VERSION
        self.session.add(meta)
        self.session.commit()
        return len(records), legal


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
            existing.event_tier = tournament.event_tier
            existing.battle_format = tournament.battle_format
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

    def list_tournament_ids_pending_standings(
        self, source_prefix: str | None = None, *, since: datetime | None = None
    ) -> set[str]:
        """Tournament IDs whose standings have never been fetched successfully.

        ``since`` limits the backlog to events on or after that date, so tournaments
        that have aged out of the sync window are not fetched or counted.
        """
        stmt = select(TournamentRecord.tournament_id).where(
            TournamentRecord.standings_synced == False  # noqa: E712 - SQL boolean column
        )
        if source_prefix:
            stmt = stmt.where(TournamentRecord.tournament_id.startswith(source_prefix))
        if since is not None:
            stmt = stmt.where(TournamentRecord.event_date >= since)
        return set(self.session.exec(stmt).all())

    def list_tournament_ids(self, source_prefix: str | None = None) -> set[str]:
        """Every stored tournament ID, optionally limited to one source prefix."""
        stmt = select(TournamentRecord.tournament_id)
        if source_prefix:
            stmt = stmt.where(TournamentRecord.tournament_id.startswith(source_prefix))
        return set(self.session.exec(stmt).all())

    def list_paste_urls_for_tournament(self, tournament_id: str) -> set[str]:
        """Paste URLs already stored for an event, so a partial ingest can resume."""
        stmt = select(TournamentTeamRecord.pokepast_url).where(
            TournamentTeamRecord.tournament_id == tournament_id,
            TournamentTeamRecord.pokepast_url.is_not(None),
        )
        return {url for url in self.session.exec(stmt).all() if url}

    def last_standings_sync_at(self) -> datetime | None:
        """When standings were last fetched successfully for any tournament."""
        return self.session.exec(
            select(func.max(TournamentRecord.updated_at)).where(TournamentRecord.standings_synced == True)  # noqa: E712
        ).one()

    # -- app state -------------------------------------------------------------------------

    def get_state(self, key: str) -> str | None:
        record = self.session.get(AppStateRecord, key)
        return record.value if record else None

    def set_state(self, key: str, value: str) -> None:
        record = self.session.get(AppStateRecord, key) or AppStateRecord(key=key)
        record.value = value
        record.updated_at = _utc_now()
        self.session.add(record)
        self.session.commit()

    def get_cached_preset_builds(self, battle_format: str | None) -> dict[str, Any] | None:
        """Retrieve cached preset builds JSON from AppStateRecord if present."""
        bformat = battle_format or "doubles"
        val = self.get_state(f"cache_preset_builds_{bformat}")
        if val:
            try:
                import json
                return json.loads(val)
            except Exception:
                pass
        return None

    def set_cached_preset_builds(self, battle_format: str | None, builds_data: dict[str, Any]) -> None:
        """Cache preset builds JSON in AppStateRecord."""
        bformat = battle_format or "doubles"
        try:
            import json
            self.set_state(f"cache_preset_builds_{bformat}", json.dumps(builds_data))
        except Exception:
            pass

    def invalidate_preset_builds_cache(self, *, commit: bool = True) -> None:
        """Invalidate cached preset builds across all formats."""
        for bformat in ("doubles", "singles", "all"):
            record = self.session.get(AppStateRecord, f"cache_preset_builds_{bformat}")
            if record:
                self.session.delete(record)
        if commit:
            try:
                self.session.commit()
            except Exception:
                self.session.rollback()

    def add_tournament_if_missing(self, tournament: TournamentRecord) -> bool:
        """Insert a discovered event; an existing row (and its sync state) is left alone."""
        if self.session.get(TournamentRecord, tournament.tournament_id) is not None:
            return False
        self.session.add(tournament)
        self.session.commit()
        return True

    def list_official_events(self, *, ended_before: datetime, pending_only: bool = True) -> list[TournamentRecord]:
        """Victory Road events that have finished — the page-read queue.

        Pokémon Champions events come first (this app is about Champions), then the
        other games; newest first within each group."""
        from sqlalchemy import case

        stmt = select(TournamentRecord).where(
            TournamentRecord.tournament_id.startswith("vr-"),
            TournamentRecord.event_date <= ended_before,
        )
        if pending_only:
            stmt = stmt.where(TournamentRecord.standings_synced == False)  # noqa: E712
        champions_first = case((TournamentRecord.game_platform == "Pokémon Champions", 0), else_=1)
        records = list(self.session.exec(stmt.order_by(champions_first, TournamentRecord.event_date.desc())).all())
        for r in records:
            self.session.expunge(r)
        return records

    def delete_teams_for_tournament(self, tournament_id: str) -> int:
        """Delete a tournament's teams and their members. Returns teams removed.

        Re-ingesting an event replaces its teams rather than appending to them, so a
        forced re-sync cannot duplicate rosters.

        Two statements rather than loading every roster row as an ORM object and deleting
        it one at a time: a large event is a few hundred rows, the sync does this per
        event, and the write lock is held while the UI reads the same file.
        """
        connection = self.session.connection()
        connection.exec_driver_sql(
            "DELETE FROM tournament_team_members WHERE tournament_team_id IN "
            "(SELECT tournament_team_id FROM tournament_teams WHERE tournament_id = ?)",
            (tournament_id,),
        )
        removed = connection.exec_driver_sql(
            "DELETE FROM tournament_teams WHERE tournament_id = ?", (tournament_id,)
        ).rowcount
        if not removed:
            # Nothing matched, so nothing to undo — and no rollback, which would discard
            # whatever else the caller has pending in this session.
            return 0
        self.invalidate_preset_builds_cache(commit=False)
        # Commit expires the session's instances, so nothing keeps a deleted row alive.
        self.session.commit()
        return int(removed)

    def list_tournaments(self) -> list[TournamentRecord]:
        return list(self.session.exec(select(TournamentRecord).order_by(TournamentRecord.event_date.desc())).all())


    def save_teams(
        self, entries: list[tuple[TournamentTeamRecord, list[TournamentTeamMemberRecord]]]
    ) -> int:
        """Persist many teams with their members in one transaction.

        Team IDs are generated client-side, so members can reference them before the
        flush. One commit per tournament instead of two per team keeps the write lock
        short — the UI reads the same file while a sync runs.
        """
        for team, members in entries:
            team.member_count = len(members)
            self.session.add(team)
            for m in members:
                m.tournament_team_id = team.tournament_team_id
                self.session.add(m)
        self.invalidate_preset_builds_cache(commit=False)
        self.session.commit()
        return len(entries)

    def save_team(
        self, team: TournamentTeamRecord, members: list[TournamentTeamMemberRecord]
    ) -> TournamentTeamRecord:
        team.member_count = len(members)
        self.session.add(team)
        self.session.commit()
        self.session.refresh(team)

        for m in members:
            m.tournament_team_id = team.tournament_team_id
            self.session.add(m)
        self.invalidate_preset_builds_cache(commit=False)
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

    def _species_ids_matching(self, raw: str, canon: str) -> list[str]:
        """Champions species whose name or id contains the query (208 rows: cheap)."""
        needle = raw.strip().lower()
        if len(needle) < 2:
            return []
        stmt = select(ChampionsSpeciesRecord.species_name, ChampionsSpeciesRecord.display_name)
        ids: list[str] = []
        for species_name, display_name in self.session.exec(stmt).all():
            sid = (species_name or "").lower()
            if not sid:
                continue
            if needle in sid or needle in (display_name or "").lower() or (canon and canon in sid):
                ids.append(sid)
        return ids

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
        event_tiers: Sequence[str] | None = None,
        tournament_id_filter: str | None = None,
        owned_species: Sequence[str] | None = None,
        max_missing: int | None = None,
        battle_format_filter: str | None = "doubles",
    ):
        """Shared WHERE clauses for search_teams and count_teams."""

        if tournament_id_filter:
            stmt = stmt.where(TournamentTeamRecord.tournament_id == tournament_id_filter)

        if battle_format_filter and battle_format_filter != "all":
            stmt = stmt.where(TournamentRecord.battle_format == battle_format_filter)

        if max_missing is not None:
            # "At most N of the roster is missing from the box": roster size minus the
            # members whose base species is owned. An empty box matches nothing.
            owned = sorted(expand_canonical_aliases(owned_species or ()))
            if not owned:
                return stmt.where(False)
            # Counted per candidate team, not as one grouped pass over every roster row:
            # the other filters (placement, recency, format) have already narrowed the
            # teams, and each count reads only that team's six rows through
            # ix_tournament_team_members_team_species. Grouping the whole members table
            # first cost ~1 s on a year of data regardless of how few teams survived.
            hits = (
                select(func.count())
                .select_from(TournamentTeamMemberRecord)
                .where(
                    TournamentTeamMemberRecord.tournament_team_id
                    == TournamentTeamRecord.tournament_team_id,
                    TournamentTeamMemberRecord.base_canonical_id.in_(owned),
                )
                .correlate(TournamentTeamRecord)
                .scalar_subquery()
            )
            missing = TournamentTeamRecord.member_count - hits
            # Closest to the box first; search_teams appends date/placement/id after this,
            # so paging keeps a total order.
            stmt = stmt.where(missing <= max_missing).order_by(missing.asc())

        if regulation_filter and regulation_filter != "All":
            stmt = stmt.where(TournamentRecord.format_regulation == regulation_filter)

        if event_tiers:
            stmt = stmt.where(TournamentRecord.event_tier.in_(list(event_tiers)))

        if game_platform_filter and game_platform_filter != "All":
            stmt = stmt.where(TournamentRecord.game_platform == game_platform_filter)

        if max_age_days is not None and max_age_days > 0:
            cutoff = _utc_now() - timedelta(days=max_age_days)
            stmt = stmt.where(TournamentRecord.event_date >= cutoff)

        if placement_filter:
            stmt = stmt.where(TournamentTeamRecord.placement <= placement_filter)

        if query:
            parsed = parse_search_query(query)

            # 1. Apply exclusions (teams containing the excluded species are omitted)
            for exc in parsed.excludes:
                exc_raw = exc.strip()
                exc_pattern = f"%{exc_raw}%"
                exc_canon = format_api_name(exc_raw)
                species_ids = self._species_ids_matching(exc_raw, exc_canon)
                if species_ids:
                    member_clause = or_(
                        TournamentTeamMemberRecord.canonical_id.in_(species_ids),
                        TournamentTeamMemberRecord.base_canonical_id.in_(species_ids),
                        *[TournamentTeamMemberRecord.canonical_id.op("GLOB")(f"{sid}-*") for sid in species_ids],
                    )
                else:
                    member_clause = (
                        (TournamentTeamMemberRecord.species_name.ilike(exc_pattern))
                        | (TournamentTeamMemberRecord.canonical_id.ilike(exc_pattern))
                        | (TournamentTeamMemberRecord.base_canonical_id.ilike(exc_pattern))
                    )
                subq_exc = select(TournamentTeamMemberRecord.tournament_team_id).where(member_clause)
                stmt = stmt.where(TournamentTeamRecord.tournament_team_id.not_in(subq_exc))
                if not species_ids:
                    stmt = stmt.where(
                        ~TournamentTeamRecord.player_name.ilike(exc_pattern),
                        ~TournamentRecord.name.ilike(exc_pattern),
                        ~TournamentTeamRecord.tournament_id.ilike(exc_pattern),
                    )

            # 2. Apply inclusions (each term must match a team member, player, event, or ID)
            for inc in parsed.includes:
                inc_raw = inc.strip()
                inc_pattern = f"%{inc_raw}%"
                inc_canon = format_api_name(inc_raw)
                c_pattern = f"%{inc_canon}%" if inc_canon else inc_pattern

                # Resolve against catalogue first: fast indexed ID lookup
                species_ids = self._species_ids_matching(inc_raw, inc_canon)
                if species_ids:
                    member_clause = or_(
                        TournamentTeamMemberRecord.canonical_id.in_(species_ids),
                        TournamentTeamMemberRecord.base_canonical_id.in_(species_ids),
                        *[TournamentTeamMemberRecord.canonical_id.op("GLOB")(f"{sid}-*") for sid in species_ids],
                    )
                else:
                    member_clause = (
                        (TournamentTeamMemberRecord.species_name.ilike(inc_pattern))
                        | (TournamentTeamMemberRecord.canonical_id.ilike(inc_pattern))
                        | (TournamentTeamMemberRecord.base_canonical_id.ilike(inc_pattern))
                        | (TournamentTeamMemberRecord.canonical_id.ilike(c_pattern))
                    )
                subq_member = select(TournamentTeamMemberRecord.tournament_team_id).where(member_clause)
                stmt = stmt.where(
                    (TournamentTeamRecord.player_name.ilike(inc_pattern))
                    | (TournamentRecord.name.ilike(inc_pattern))
                    | (TournamentTeamRecord.tournament_id.ilike(inc_pattern))
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
        event_tiers: Sequence[str] | None = None,
        tournament_id_filter: str | None = None,
        owned_species: Sequence[str] | None = None,
        max_missing: int | None = None,
        battle_format_filter: str | None = "doubles",
    ) -> list[TournamentTeamRecord]:
        stmt = self._apply_search_filters(
            self._joined_teams(),
            query=query,
            regulation_filter=regulation_filter,
            placement_filter=placement_filter,
            species_filter=species_filter,
            game_platform_filter=game_platform_filter,
            max_age_days=max_age_days,
            event_tiers=event_tiers,
            tournament_id_filter=tournament_id_filter,
            owned_species=owned_species,
            max_missing=max_missing,
            battle_format_filter=battle_format_filter,
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
        event_tiers: Sequence[str] | None = None,
        tournament_id_filter: str | None = None,
        owned_species: Sequence[str] | None = None,
        max_missing: int | None = None,
        battle_format_filter: str | None = "doubles",
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
            event_tiers=event_tiers,
            tournament_id_filter=tournament_id_filter,
            owned_species=owned_species,
            max_missing=max_missing,
            battle_format_filter=battle_format_filter,
        )
        return int(self.session.exec(select(func.count()).select_from(stmt.subquery())).one() or 0)

    def move_usage(self, canonical_id: str, *, include_megas: bool = True, battle_format: str | None = "doubles") -> list[tuple[str, int]]:
        """(move name, rosters using it) for a species across every stored team, most used first.

        Mega forms share the base species' moves, so "charizard" counts "charizard-mega-y"
        rosters too when ``include_megas`` is set.
        """
        from sqlalchemy import text as _text

        base = canonical_id.lower()
        params: dict[str, Any] = {"cid": base}
        if include_megas:
            # A range rather than LIKE ':base-mega%': identical rows (ids are lowercase),
            # but SQLite can answer it from ix_tournament_team_members_canonical_id
            # instead of scanning every roster row. "megb" is "mega" with the last letter
            # bumped, so the range is exactly the "<base>-mega…" prefix.
            clause = "m.canonical_id = :cid OR (m.canonical_id >= :mega_lo AND m.canonical_id < :mega_hi)"
            params["mega_lo"] = f"{base}-mega"
            params["mega_hi"] = f"{base}-megb"
        else:
            clause = "m.canonical_id = :cid"
        joins = ""
        extra = ""
        if battle_format and battle_format != "all":
            # A positive join on the matched rows only. The old NOT IN (…) anti-join
            # materialised every team of the other formats before the species filter ran.
            joins = (
                "JOIN tournament_teams tt ON tt.tournament_team_id = m.tournament_team_id "
                "JOIN tournaments tr ON tr.tournament_id = tt.tournament_id "
            )
            extra = "AND tr.battle_format = :bformat "
            params["bformat"] = battle_format
        rows = self.session.exec(
            _text(
                f"SELECT j.value AS move, COUNT(*) AS n FROM tournament_team_members m {joins}, json_each(m.moves) j "
                f"WHERE ({clause}) {extra}GROUP BY j.value ORDER BY n DESC, move ASC"
            ).bindparams(**params)
        ).all()
        return [(str(move), int(n)) for move, n in rows if move]

    def move_usage_all(self, *, battle_format: str | None = "doubles") -> dict[str, list[tuple[str, int]]]:
        """{base species id: [(move name, rosters using it), …] most used first} for every species
        in one query (megas fold into their base species)."""
        from sqlalchemy import text as _text

        where = ""
        params: dict[str, Any] = {}
        if battle_format and battle_format != "all":
            # The format-matching teams are collected once and probed, instead of looking
            # the team and its tournament up again for each of the ~400 k roster rows.
            where = (
                "AND m.tournament_team_id IN ("
                "SELECT tt.tournament_team_id FROM tournament_teams tt "
                "JOIN tournaments tr ON tt.tournament_id = tr.tournament_id "
                "WHERE tr.battle_format = :bformat) "
            )
            params["bformat"] = battle_format
        rows = self.session.exec(
            _text(
                "SELECT m.base_canonical_id AS cid, j.value AS move, COUNT(*) AS n "
                "FROM tournament_team_members m, json_each(m.moves) j "
                f"WHERE m.base_canonical_id != '' {where}GROUP BY cid, j.value ORDER BY cid, n DESC, move ASC"
            ).bindparams(**params)
        ).all()
        out: dict[str, list[tuple[str, int]]] = {}
        for cid, move, n in rows:
            if move:
                out.setdefault(str(cid), []).append((str(move), int(n)))
        return out

    def nature_usage_all(self, *, battle_format: str | None = "doubles") -> dict[str, list[tuple[str, int]]]:
        """{base species id: [(nature, count), …] most used first} for every species."""
        from sqlalchemy import text as _text

        joins = ""
        where = ""
        params: dict[str, Any] = {}
        if battle_format and battle_format != "all":
            joins = "JOIN tournament_teams tt ON m.tournament_team_id = tt.tournament_team_id JOIN tournaments tr ON tt.tournament_id = tr.tournament_id "
            where = "AND tr.battle_format = :bformat "
            params["bformat"] = battle_format
        rows = self.session.exec(
            _text(
                "SELECT m.base_canonical_id AS base_cid, m.canonical_id AS cid, LOWER(m.nature) AS nature, COUNT(*) AS n "
                f"FROM tournament_team_members m {joins}"
                f"WHERE (m.base_canonical_id != '' OR m.canonical_id != '') AND m.nature IS NOT NULL AND m.nature != '' {where}"
                "GROUP BY base_cid, cid, LOWER(m.nature) ORDER BY n DESC"
            ).bindparams(**params)
        ).all()
        out: dict[str, list[tuple[str, int]]] = {}
        for base_cid, cid, nat, n in rows:
            if nat:
                target_keys = {str(base_cid), str(cid)} - {""}
                for k in target_keys:
                    out.setdefault(k, []).append((str(nat), int(n)))
        return out

    def item_usage_all(self, *, battle_format: str | None = "doubles") -> dict[str, list[tuple[str, int]]]:
        """{species id: [(item, count), …] most used first} for every species."""
        from sqlalchemy import text as _text

        joins = ""
        where = ""
        params: dict[str, Any] = {}
        if battle_format and battle_format != "all":
            joins = "JOIN tournament_teams tt ON m.tournament_team_id = tt.tournament_team_id JOIN tournaments tr ON tt.tournament_id = tr.tournament_id "
            where = "AND tr.battle_format = :bformat "
            params["bformat"] = battle_format
        rows = self.session.exec(
            _text(
                "SELECT m.base_canonical_id AS base_cid, m.canonical_id AS cid, m.item AS item, COUNT(*) AS n "
                f"FROM tournament_team_members m {joins}"
                f"WHERE (m.base_canonical_id != '' OR m.canonical_id != '') AND m.item IS NOT NULL AND m.item != '' {where}"
                "GROUP BY base_cid, cid, m.item ORDER BY n DESC"
            ).bindparams(**params)
        ).all()
        out: dict[str, list[tuple[str, int]]] = {}
        for base_cid, cid, itm, n in rows:
            if itm:
                target_keys = {str(base_cid), str(cid)} - {""}
                for k in target_keys:
                    out.setdefault(k, []).append((str(itm), int(n)))
        return out

    def ability_usage_all(self, *, battle_format: str | None = "doubles") -> dict[str, list[tuple[str, int]]]:
        """{species id: [(ability, count), …] most used first} for every species."""
        from sqlalchemy import text as _text

        joins = ""
        where = ""
        params: dict[str, Any] = {}
        if battle_format and battle_format != "all":
            joins = "JOIN tournament_teams tt ON m.tournament_team_id = tt.tournament_team_id JOIN tournaments tr ON tt.tournament_id = tr.tournament_id "
            where = "AND tr.battle_format = :bformat "
            params["bformat"] = battle_format
        rows = self.session.exec(
            _text(
                "SELECT m.base_canonical_id AS base_cid, m.canonical_id AS cid, m.ability AS ability, COUNT(*) AS n "
                f"FROM tournament_team_members m {joins}"
                f"WHERE (m.base_canonical_id != '' OR m.canonical_id != '') AND m.ability IS NOT NULL AND m.ability != '' {where}"
                "GROUP BY base_cid, cid, m.ability ORDER BY n DESC"
            ).bindparams(**params)
        ).all()
        out: dict[str, list[tuple[str, int]]] = {}
        for base_cid, cid, ab, n in rows:
            if ab:
                target_keys = {str(base_cid), str(cid)} - {""}
                for k in target_keys:
                    out.setdefault(k, []).append((str(ab), int(n)))
        return out

    def list_regulations(self) -> list[str]:
        """Distinct regulation labels present in the data, most common first."""
        stmt = (
            select(TournamentRecord.format_regulation, func.count())
            .group_by(TournamentRecord.format_regulation)
            .order_by(func.count().desc())
        )
        return [reg for reg, _n in self.session.exec(stmt).all() if reg]

    def get_latest_regulation(self, game_platform: str | None = None) -> str:
        """The most recent regulation label based on the newest tournament event date."""
        from sqlalchemy import text as _text

        extra = "AND game_platform = :platform" if game_platform else ""
        params = {"platform": game_platform} if game_platform else {}
        stmt = _text(
            "SELECT format_regulation FROM tournaments "
            f"WHERE format_regulation IS NOT NULL AND format_regulation != '' AND format_regulation != 'CUSTOM' {extra} "
            "GROUP BY format_regulation ORDER BY MAX(event_date) DESC LIMIT 1"
        ).bindparams(**params)
        row = self.session.exec(stmt).first()
        return str(row[0]) if row and row[0] else "Regulation M-C"

    def list_regulations_by_date(self, game_platform: str | None = None) -> list[str]:
        """Distinct regulation labels ordered chronologically from newest event date to oldest."""
        from sqlalchemy import text as _text

        extra = "AND game_platform = :platform" if game_platform else ""
        params = {"platform": game_platform} if game_platform else {}
        stmt = _text(
            "SELECT format_regulation FROM tournaments "
            f"WHERE format_regulation IS NOT NULL AND format_regulation != '' AND format_regulation != 'CUSTOM' {extra} "
            "GROUP BY format_regulation ORDER BY MAX(event_date) DESC"
        ).bindparams(**params)
        rows = self.session.exec(stmt).all()
        return [str(r[0]) for r in rows if r and r[0]]

    def species_usage_by_regulation(
        self, regulation: str | None = None, battle_format: str | None = "doubles"
    ) -> dict[str, int]:
        """{canonical_id / base_species_id: team_count} for the given regulation and battle format.

        Returns distinct team counts per species. Mega forms fold into their base species
        so that e.g. 'charizard' counts both Charizard and Mega Charizards, while also
        recording form-specific keys.
        """
        from sqlalchemy import text as _text

        extra = []
        params: dict[str, Any] = {}
        if regulation and regulation != "All":
            extra.append("t.format_regulation = :reg")
            params["reg"] = regulation
        if battle_format and battle_format != "all":
            extra.append("t.battle_format = :bformat")
            params["bformat"] = battle_format
        where_clause = f"WHERE {' AND '.join(extra)}" if extra else ""

        stmt = _text(
            "SELECT m.base_canonical_id AS base_cid, m.canonical_id AS cid, "
            "       COUNT(*) AS n "
            "FROM tournament_team_members m "
            "JOIN tournament_teams tt ON m.tournament_team_id = tt.tournament_team_id "
            "JOIN tournaments t ON tt.tournament_id = t.tournament_id "
            f"{where_clause} "
            "GROUP BY base_cid, cid"
        ).bindparams(**params)
        rows = self.session.exec(stmt).all()
        out: dict[str, int] = {}
        for base_cid, cid, n in rows:
            count = int(n or 0)
            b_key = str(base_cid or "").lower()
            c_key = str(cid or "").lower()
            if b_key:
                out[b_key] = out.get(b_key, 0) + count
            if c_key and c_key != b_key:
                out[c_key] = out.get(c_key, 0) + count
        return out

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
                event_tier=classify_event_tier(t_dict.get("name"), t_dict.get("organizer", "Official VGC")),
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
                showdown_text = team_dict.get("showdown_text", "")
                try:
                    from pokemon_champions_planning_tool.services.showdown_service import parse_showdown_text
                    parsed_slots = list(parse_showdown_text(showdown_text).slots)
                except Exception:
                    parsed_slots = []
                from pokemon_champions_planning_tool.domain.pokemon_identity import base_canonical_id
                members = []
                for idx, mem in enumerate(team_dict.get("members", []), start=1):
                    slot = parsed_slots[idx - 1] if idx - 1 < len(parsed_slots) else None
                    cid = mem["canonical_id"]
                    members.append(
                        TournamentTeamMemberRecord(
                            slot_position=idx,
                            canonical_id=cid,
                            species_name=mem["species_name"],
                            base_canonical_id=base_canonical_id(cid),
                            moves=list(slot.moves) if (slot and slot.moves) else [],
                            nature=slot.nature.lower() if (slot and slot.nature) else None,
                            item=slot.item_name if slot else None,
                            ability=slot.ability_name if slot else None,
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