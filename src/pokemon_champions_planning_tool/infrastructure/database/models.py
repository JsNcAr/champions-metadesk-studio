"""SQLModel table definitions for the local SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel

from ...domain.entities.box_entry import BoxEntry
from ...domain.entities.pokemon import Pokemon
from ...domain.entities.pokemon_ability import PokemonAbility
from ...domain.entities.pokemon_form import PokemonForm
from ...domain.entities.pokemon_move import PokemonMove
from ...domain.entities.pokemon_stats import PokemonStats
from ...domain.entities.team import Team
from ...domain.entities.team_member import TeamMember


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PokemonRecord(SQLModel, table=True):
    """Persisted Pokemon snapshot used by the box and team layers."""

    __tablename__: ClassVar[str] = "pokemon_records"

    canonical_id: str = Field(primary_key=True, index=True)
    display_name: str
    species_name: str | None = None
    form_name: str = Field(default="Base")
    dex_number: int | None = Field(default=None, index=True)
    types: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    sprite_url: str | None = None
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    abilities: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    moves: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    available_forms: list[dict[str, Any]] = Field(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def from_domain(cls, pokemon: Pokemon) -> "PokemonRecord":
        return cls(
            canonical_id=pokemon.canonical_id,
            display_name=pokemon.display_name,
            species_name=pokemon.species_name,
            form_name=pokemon.form_name,
            dex_number=pokemon.dex_number,
            types=list(pokemon.types),
            sprite_url=pokemon.sprite_url,
            hp=pokemon.stats.hp,
            attack=pokemon.stats.attack,
            defense=pokemon.stats.defense,
            special_attack=pokemon.stats.special_attack,
            special_defense=pokemon.stats.special_defense,
            speed=pokemon.stats.speed,
            abilities=[ability.model_dump(mode="json") for ability in pokemon.abilities],
            moves=[move.model_dump(mode="json") for move in pokemon.moves],
            available_forms=[form.model_dump(mode="json") for form in pokemon.available_forms],
        )

    def to_domain(self) -> Pokemon:
        return Pokemon(
            canonical_id=self.canonical_id,
            display_name=self.display_name,
            species_name=self.species_name,
            form_name=self.form_name,
            dex_number=self.dex_number,
            types=list(self.types),
            sprite_url=self.sprite_url,
            stats=PokemonStats(
                hp=self.hp,
                attack=self.attack,
                defense=self.defense,
                sp_atk=self.special_attack,
                sp_def=self.special_defense,
                speed=self.speed,
            ),
            abilities=[PokemonAbility.model_validate(ability) for ability in self.abilities],
            moves=[PokemonMove.model_validate(move) for move in self.moves],
            available_forms=[PokemonForm.model_validate(form) for form in self.available_forms],
        )


class BoxEntryRecord(SQLModel, table=True):
    """Persisted user box entry linked to a canonical Pokemon record."""

    __tablename__: ClassVar[str] = "box_entries"

    box_entry_id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    pokemon_canonical_id: str = Field(
        foreign_key="pokemon_records.canonical_id", unique=True, index=True
    )
    notes: str = ""
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_favorite: bool = False
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def from_domain(cls, box_entry: BoxEntry) -> "BoxEntryRecord":
        return cls(
            pokemon_canonical_id=box_entry.pokemon.canonical_id,
            notes=box_entry.notes,
            tags=list(box_entry.tags),
            is_favorite=box_entry.is_favorite,
            created_at=box_entry.created_at,
            updated_at=box_entry.updated_at,
        )

    def to_domain(self, pokemon: Pokemon) -> BoxEntry:
        return BoxEntry(
            box_entry_id=self.box_entry_id,
            pokemon=pokemon,
            notes=self.notes,
            tags=list(self.tags),
            is_favorite=self.is_favorite,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class TeamRecord(SQLModel, table=True):
    """Persisted team metadata."""

    __tablename__: ClassVar[str] = "teams"

    team_id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(index=True)
    description: str = ""
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def from_domain(cls, team: Team) -> "TeamRecord":
        return cls(
            team_id=team.team_id,
            name=team.name,
            description=team.description,
            created_at=team.created_at,
            updated_at=team.updated_at,
        )

    def to_domain(self, members: list[TeamMember] | None = None) -> Team:
        return Team(
            team_id=self.team_id,
            name=self.name,
            description=self.description,
            members=members or [],
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class TeamMemberRecord(SQLModel, table=True):
    """Persisted team slot assignment."""

    __tablename__: ClassVar[str] = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "slot_position", name="uq_team_slot"),)

    team_member_id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    team_id: UUID = Field(foreign_key="teams.team_id", index=True)
    box_entry_id: UUID = Field(foreign_key="box_entries.box_entry_id", index=True)
    slot_position: int = Field(index=True)
    item: str | None = None
    moveset: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    ability: str | None = None
    notes: str = ""

    @classmethod
    def from_domain(cls, team_id: UUID, team_member: TeamMember) -> "TeamMemberRecord":
        return cls(
            team_member_id=team_member.team_member_id,
            team_id=team_id,
            box_entry_id=team_member.box_entry_id,
            slot_position=team_member.slot_position,
            item=team_member.item,
            moveset=[move.model_dump(mode="json") for move in team_member.moveset],
            ability=team_member.ability,
            notes=team_member.notes,
        )
