"""SQLModel table definitions for the local SQLite database."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey, JSON, Text, UniqueConstraint

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
    """Persisted user box entry linked to a canonical Pokemon record.

    ``is_planned`` marks ghost/template entries that exist on a team plan but
    have not yet been caught/owned by the user.  Planned entries are excluded
    from the main box grid but remain valid FK targets for TeamMemberRecord.
    """

    __tablename__: ClassVar[str] = "box_entries"

    box_entry_id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    # unique=True removed — uniqueness is enforced at the repository layer for
    # non-planned entries only (a Pokémon can have one real + one planned entry).
    pokemon_canonical_id: str = Field(
        foreign_key="pokemon_records.canonical_id", index=True
    )
    notes: str = ""
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_favorite: bool = False
    is_planned: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @classmethod
    def from_domain(cls, box_entry: BoxEntry) -> "BoxEntryRecord":
        return cls(
            pokemon_canonical_id=box_entry.pokemon.canonical_id,
            notes=box_entry.notes,
            tags=list(box_entry.tags),
            is_favorite=box_entry.is_favorite,
            is_planned=box_entry.is_planned,
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
            is_planned=self.is_planned,
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
    """Persisted team slot assignment.

    ``evs`` and ``ivs`` store competitive EV/IV spreads as dicts mapping stat
    keys (``hp``, ``attack``, ``defense``, ``special_attack``,
    ``special_defense``, ``speed``) to integer values.  Only non-zero EVs and
    non-31 IVs need to be stored; missing keys imply 0 EVs / 31 IVs.
    """

    __tablename__: ClassVar[str] = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "slot_position", name="uq_team_slot"),)

    team_member_id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    team_id: UUID = Field(foreign_key="teams.team_id", index=True)
    box_entry_id: UUID = Field(foreign_key="box_entries.box_entry_id", index=True)
    slot_position: int = Field(index=True)
    selected_form: str = Field(default="base")
    item: str | None = None
    moveset: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    ability: str | None = None
    notes: str = ""
    # Competitive spread fields
    evs: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    ivs: dict[str, int] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    nature: str | None = None
    level: int = Field(default=50)
    tera_type: str | None = None

    @classmethod
    def from_domain(cls, team_id: UUID, team_member: TeamMember) -> "TeamMemberRecord":
        return cls(
            team_member_id=team_member.team_member_id,
            team_id=team_id,
            box_entry_id=team_member.box_entry_id,
            slot_position=team_member.slot_position,
            selected_form=getattr(team_member, "selected_form", "base"),
            item=team_member.item,
            moveset=[move.model_dump(mode="json") for move in team_member.moveset],
            ability=team_member.ability,
            notes=team_member.notes,
            evs=dict(team_member.evs or {}),
            ivs=dict(team_member.ivs or {}),
            nature=team_member.nature,
            level=team_member.level,
            tera_type=team_member.tera_type,
        )

    def to_domain(self) -> TeamMember:
        return TeamMember(
            team_member_id=self.team_member_id,
            box_entry_id=self.box_entry_id,
            slot_position=self.slot_position,
            selected_form=self.selected_form or "base",
            item=self.item,
            moveset=[PokemonMove.model_validate(move) for move in (self.moveset or [])],
            ability=self.ability,
            notes=self.notes or "",
            evs=dict(self.evs or {}),
            ivs=dict(self.ivs or {}),
            nature=self.nature,
            level=self.level or 50,
            tera_type=self.tera_type,
        )



class ChampionsSpeciesRecord(SQLModel, table=True):
    """Persisted Champions Pokédex catalog species record."""

    __tablename__: ClassVar[str] = "champions_species"

    entry_number: int = Field(primary_key=True)
    species_name: str = Field(index=True, unique=True)
    display_name: str
    created_at: datetime = Field(default_factory=_utc_now)


class MegaEvolutionRecord(SQLModel, table=True):
    """Persisted Mega Evolution record with stats, typing, and sprite."""

    __tablename__: ClassVar[str] = "mega_evolutions"

    canonical_id: str = Field(primary_key=True, index=True)
    species_name: str = Field(index=True)
    display_name: str
    form_name: str = Field(default="Mega")
    types: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    sprite_url: str | None = None
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int
    created_at: datetime = Field(default_factory=_utc_now)


class MegaCheckedSpeciesRecord(SQLModel, table=True):
    """Tracks species that have already been checked for Mega Evolutions in PokéAPI."""

    __tablename__: ClassVar[str] = "mega_checked_species"

    species_name: str = Field(primary_key=True, index=True)
    checked_at: datetime = Field(default_factory=_utc_now)




class ItemRecord(SQLModel, table=True):
    """Persisted held item with Champions format legality and stat modifier data."""

    __tablename__: ClassVar[str] = "item_records"

    canonical_id: str = Field(primary_key=True, index=True)
    display_name: str
    category: str = Field(default="other", index=True)
    is_champions_legal: bool = Field(default=True, index=True)
    sprite_url: str | None = None
    short_effect: str = Field(default="")
    target_species: str | None = Field(default=None, index=True)
    target_form: str | None = None
    stat_modifiers: dict[str, float] = Field(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    def to_domain(self) -> "Item":
        from ...domain.entities.item import Item
        return Item(
            canonical_id=self.canonical_id,
            display_name=self.display_name,
            category=self.category,
            is_champions_legal=self.is_champions_legal,
            sprite_url=self.sprite_url,
            short_effect=self.short_effect,
            target_species=self.target_species,
            target_form=self.target_form,
            stat_modifiers=dict(self.stat_modifiers),
        )


class ItemCatalogMetaRecord(SQLModel, table=True):
    """Singleton row tracking the last successful item catalog sync.

    id is always 1. Used for staleness detection: compare total_holdable_items
    against the live count from Showdown to decide whether to re-sync.
    """

    __tablename__: ClassVar[str] = "item_catalog_meta"

    id: int = Field(default=1, primary_key=True)
    total_holdable_items: int = Field(default=0)
    last_synced_at: datetime = Field(default_factory=_utc_now)


# ---------------------------------------------------------------------------
# Tournament & Meta Explorer Records
# ---------------------------------------------------------------------------


class TournamentRecord(SQLModel, table=True):
    """Persisted VGC Tournament metadata."""

    __tablename__: ClassVar[str] = "tournaments"

    tournament_id: str = Field(primary_key=True, index=True)
    name: str = Field(index=True)
    event_date: datetime = Field(default_factory=_utc_now, index=True)
    format_regulation: str = Field(index=True)
    game_platform: str = Field(default="Scarlet & Violet", index=True)
    organizer: str = Field(default="Official VGC")
    location: str = Field(default="Honolulu, HI")
    total_players: int = Field(default=0)
    source_url: str | None = None
    # False until a standings fetch for this tournament has actually succeeded.
    # The sync caps standings requests per run to respect rate limits, so unsynced
    # tournaments form a backlog that later runs drain instead of skipping forever.
    standings_synced: bool = Field(default=False, index=True)
    # "worlds" | "international" | "regional" | "special" (official Play! Pokémon) or
    # "community". See domain/event_tier.py; set on ingest and backfilled by migration.
    event_tier: str = Field(default="community", index=True)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class TournamentTeamRecord(SQLModel, table=True):
    """Persisted tournament team standing & submission."""

    __tablename__: ClassVar[str] = "tournament_teams"

    tournament_team_id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    tournament_id: str = Field(foreign_key="tournaments.tournament_id", index=True)
    player_name: str = Field(index=True)
    placement: int = Field(index=True)
    standing_label: str = Field(default="Top 8")
    pokepast_url: str | None = None
    showdown_text: str = Field(sa_column=Column(Text, nullable=False))
    source_dataset: str = Field(default="seed_v1", index=True)
    sync_source: str = Field(default="seed", index=True)
    # Age division this roster placed in. Only "masters" is ingested; premier events
    # publish Seniors/Juniors on the same page with placements restarting at 1.
    division: str = Field(default="masters", index=True)
    # Roster size, kept on the team so the Box filter needs one indexed pass over the
    # owned members instead of grouping every roster row per query.
    member_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utc_now)



class TournamentTeamMemberRecord(SQLModel, table=True):
    """Normalized species entries for fast synergy and filtering queries."""

    __tablename__: ClassVar[str] = "tournament_team_members"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    tournament_team_id: UUID = Field(foreign_key="tournament_teams.tournament_team_id", index=True)
    slot_position: int = Field(default=1)
    canonical_id: str = Field(index=True)
    species_name: str = Field(index=True)
    # Move names as written in the paste, so per-species usage can be aggregated with
    # json_each() instead of re-parsing every Showdown text.
    moves: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    # Mega-stripped species id ("charizard" for "charizard-mega-y"; forms such as
    # "rotom-wash" stay as they are) so "is this roster member in my box?" is an
    # indexed IN() instead of a pattern match. Set on ingest, backfilled by migration.
    base_canonical_id: str = Field(default="", index=True)


class MoveRecord(SQLModel, table=True):
    """One move from Showdown's data, with Champions overrides applied."""

    __tablename__: ClassVar[str] = "moves"

    move_id: str = Field(primary_key=True)   # Showdown id, e.g. "fakeout"
    name: str = Field(index=True)
    type: str | None = None
    category: str | None = None
    power: int | None = None
    accuracy: int | None = None
    pp: int | None = None
    priority: int = Field(default=0)
    target: str | None = None
    short_desc: str | None = None
    is_legal: bool = Field(default=True, index=True)  # False: removed from Champions


class LearnsetRecord(SQLModel, table=True):
    """A (species key, move id) pair: the species can learn the move in Champions."""

    __tablename__: ClassVar[str] = "learnsets"

    species_key: str = Field(primary_key=True)
    move_id: str = Field(primary_key=True)


class MoveCatalogMetaRecord(SQLModel, table=True):
    """Singleton row: when the move catalogue was last synced and how big it is."""

    __tablename__: ClassVar[str] = "move_catalog_meta"

    id: int = Field(default=1, primary_key=True)
    move_count: int = Field(default=0)
    learnset_count: int = Field(default=0)
    species_count: int = Field(default=0)
    last_synced_at: datetime = Field(default_factory=_utc_now)


class AppStateRecord(SQLModel, table=True):
    """Small key/value store for sync bookkeeping (e.g. when a calendar was last checked)."""

    __tablename__: ClassVar[str] = "app_state"

    key: str = Field(primary_key=True)
    value: str = Field(default="")
    updated_at: datetime = Field(default_factory=_utc_now)


class TournamentSeedMetaRecord(SQLModel, table=True):
    """Tracks tournament seed dataset loading status."""

    __tablename__: ClassVar[str] = "tournament_seed_meta"

    id: int = Field(default=1, primary_key=True)
    seed_version: str = Field(default="seed_v1")
    total_tournaments: int = Field(default=0)
    total_teams: int = Field(default=0)
    loaded_at: datetime = Field(default_factory=_utc_now)

