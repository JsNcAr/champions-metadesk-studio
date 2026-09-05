# Data Model

This document outlines the core domain entities and SQLModel database persistence records implemented in the Pokemon Champions Planning Tool.

## Core Domain Entities (Pydantic / Dataclasses)

The domain layer uses a mix of Pydantic models (for API validation and serialization) and standard Python dataclasses (for business logic containers).

### `Pokemon` (Pydantic BaseModel)
Represents a specific Pokemon species/form and its API-backed attributes.
- `canonical_id: str` — Stable PokéAPI identifier (e.g. `"pikachu"`, `"charizard-mega-x"`).
- `display_name: str` — Human-readable name (e.g. `"Pikachu"`, `"Mega Charizard X"`).
- `species_name: str | None` — Base species name when the record represents a specific form.
- `form_name: str` — Form label such as `"Base"`, `"Mega"`, or `"Regional"`; for species whose bare id names a specific default form it is that form (`"basculegion"` → `"Male"`, `"aegislash"` → `"Shield"`, see `DEFAULT_FORM_LABELS` in `domain/pokemon_identity.py`). `Pokemon.qualified_name` renders `"Basculegion (Male)"` and the UI shows the label as a caption on cards and rows.
- `dex_number: int | None` — National Pokédex number when available.
- `types: list[str]` — Primary and secondary Pokemon types.
- `sprite_url: str | None` — Default sprite or artwork URL.
- `stats: PokemonStats` — Validated base stat block.
- `abilities: list[PokemonAbility]` — Known abilities for this Pokemon or form.
- `moves: list[PokemonMove]` — Known or selected moves associated with the Pokemon.
- `available_forms: list[PokemonForm]` — Other forms that can be selected.
- `@property total -> int` — Computed property returning the sum of all base stats.

### `PokemonStats` (Pydantic BaseModel)
Represents the base stat block.
- `hp: int`
- `attack: int`
- `defense: int`
- `special_attack: int` (aliased to `sp_atk`)
- `special_defense: int` (aliased to `sp_def`)
- `speed: int`
- `@property total -> int` — Derived sum of all 6 base stats.

### `PokemonAbility` (Pydantic BaseModel)
- `name: str` — Ability name.
- `slot: int | None` — Ability slot number.
- `is_hidden: bool` — Whether the ability is hidden.
- `url: str | None` — PokéAPI URL for the ability details.

### `PokemonForm` (Pydantic BaseModel)
- `form_id: str` — Stable identifier for the form.
- `display_name: str` — Human-readable form name.
- `is_mega: bool` — Whether it is a Mega form.
- `is_regional: bool` — Whether it is a regional variant.
- `sprite_url: str | None` — Sprite/artwork URL for the form.
- `type_override: list[str]` — Types that override the base Pokemon types.

### `PokemonMove` (Pydantic BaseModel)
- `name: str` — Move name.
- `type: str | None` — Move type.
- `power: int | None` — Base power.
- `accuracy: int | None` — Accuracy percentage.
- `category: str | None` — Physical, special, or status.
- `priority: int` — Move priority.
- `learn_method: str | None` — How the move is learned.
- `level_learned_at: int | None` — Level at which the move is learned.

### `Item` (Pydantic BaseModel)
Represents a held item or Mega Stone with metadata and stat effects.
- `canonical_id: str` — Stable slug identifier (e.g. `"choice-scarf"`, `"charizardite-x"`).
- `display_name: str` — Human-readable name shown in the UI (e.g. `"Choice Scarf"`).
- `category: str` — Category (`"mega_stone"`, `"choice"`, `"held-items"`, `"other"`).
- `is_champions_legal: bool` — Legality in the Champions format.
- `sprite_url: str | None` — Sprite URL.
- `short_effect: str` — Concise English effect description.
- `target_species: str | None` — Target species slug for Mega Stones (`"charizard"`).
- `target_form: str | None` — Target Mega form slug (`"mega-x"`, `"mega-y"`).
- `stat_modifiers: dict[str, float]` — Stat multipliers when held (`{"speed": 1.5}`).
- `@property is_mega_stone -> bool` — Derived helper checking whether the category is `"mega_stone"`.

### `BoxEntry` (Standard Python Dataclass)
Represents a user's stored Pokemon in their box.
- `box_entry_id: UUID` — Unique identifier (default: auto-generated `uuid4`).
- `pokemon: Pokemon` — Domain Pokemon entity.
- `notes: str` — User-supplied notes or nicknames.
- `tags: list[str]` — Custom tags for filtering (e.g. `["lead", "sweeper"]`).
- `is_favorite: bool` — Mark as favorite.
- `is_planned: bool` — Mark as template/ghost entry (not owned yet, stays on team plan without cluttering box).
- `created_at: datetime` — Timestamp of creation (UTC).
- `updated_at: datetime` — Timestamp of last modification (UTC).

### `Team` (Standard Python Dataclass)
Represents a user-created squad or team.
- `team_id: UUID` — Unique identifier.
- `name: str` — Team name.
- `description: str` — Detailed team notes.
- `members: list[TeamMember]` — List of slot assignments.
- `created_at: datetime`
- `updated_at: datetime`

### `TeamMember` (Standard Python Dataclass)
Represents one box entry assigned to a specific team slot.
- `team_member_id: UUID` — Unique identifier.
- `box_entry_id: UUID` — Foreign reference to a `BoxEntry`.
- `slot_position: int` — Team slot position index (1-6).
- `selected_form: str` — Selected form identifier (`"base"`, `"mega"`, etc.).
- `item: str | None` — Held item canonical ID.
- `moveset: list[PokemonMove]` — Assigned moves.
- `ability: str | None` — Chosen ability.
- `notes: str` — Slot-specific comments.
- `points: dict[str, int]` — Champions stat points per stat key (0–32 each, 66 in total); only invested stats are present.
- `nature: str | None` — Nature name.
- `level: int` — Battle level (fixed at 50 in Champions).
- `tera_type: str | None` — Tera type (lowercase name; kept for Showdown pastes).

---

## SQLite Database Schemas (SQLModel Tables)

Database models in `src/pokemon_champions_planning_tool/infrastructure/database/models.py` map these domain structures directly to SQL tables via SQLModel.

### `PokemonRecord` (Table: `pokemon_records`)
- `canonical_id: str` (Primary Key, Indexed)
- `display_name: str`
- `species_name: str | None`
- `form_name: str`
- `dex_number: int | None` (Indexed)
- `types: list[str]` (Stored as JSON array)
- `sprite_url: str | None`
- `hp: int`
- `attack: int`
- `defense: int`
- `special_attack: int`
- `special_defense: int`
- `speed: int`
- `abilities: list[dict]` (Stored as JSON array)
- `moves: list[dict]` (Stored as JSON array)
- `available_forms: list[dict]` (Stored as JSON array)
- `is_placeholder: bool` (default: False, temporary flag during lookups)
- `created_at: datetime`
- `updated_at: datetime`

### `BoxEntryRecord` (Table: `box_entries`)
- `box_entry_id: UUID` (Primary Key, Indexed)
- `pokemon_canonical_id: str` (Foreign Key -> `pokemon_records.canonical_id`, Indexed; uniqueness is enforced at repository level for non-planned entries)
- `notes: str`
- `tags: list[str]` (Stored as JSON array)
- `is_favorite: bool`
- `is_planned: bool` (Indexed; default False, allows team planning templates without cluttering the main box roster)
- `created_at: datetime`
- `updated_at: datetime`

### `TeamRecord` (Table: `teams`)
- `team_id: UUID` (Primary Key, Indexed)
- `name: str` (Indexed)
- `description: str`
- `created_at: datetime`
- `updated_at: datetime`

### `TeamMemberRecord` (Table: `team_members`)
- `team_member_id: UUID` (Primary Key, Indexed)
- `team_id: UUID` (Foreign Key -> `teams.team_id`, Indexed)
- `box_entry_id: UUID` (Foreign Key -> `box_entries.box_entry_id`, Indexed)
- `slot_position: int` (Indexed)
- `selected_form: str` (default: `"base"`, selected Mega or regional variant)
- `item: str | None`
- `moveset: list[dict]` (Stored as JSON array)
- `ability: str | None`
- `notes: str`
- `points: dict` (JSON) — Champions stat points; `nature: str | None`; `level: int` (pinned to 50); `tera_type: str | None`
- `evs`, `ivs` (JSON) — legacy mainline spread columns. The initialisation backfill converts an EV dict into `points` with `(EV + 4) // 8` (which keeps every level-50 stat), then clears the legacy columns.
- *Constraints*: Table-level Unique Constraint `uq_team_slot` on `(team_id, slot_position)` to guarantee one member per slot.

### `SpeciesRecord` (Table: `species_catalog`)
- `showdown_id: str` (Primary Key) — "charizardmegay"; `canonical_id: str` (Indexed) — "charizard-mega-y"; `name: str` — "Charizard-Mega-Y"
- `dex_number: int`, `base_species_id: str`, `forme: str | None`, `types: list[str]` (JSON, capitalised)
- `hp, attack, defense, special_attack, special_defense, speed: int` — base stats
- `abilities: list[str]` (JSON, slots 0/1/H), `hidden_ability: str | None`, `weightkg: float`, `gender: str | None`
- `required_item: str | None` (Mega Stone), `battle_only: str | None`, `is_mega: bool`, `is_legal: bool` (Champions legality from the mod's formats data)
- `SpeciesCatalogMetaRecord` (`species_catalog_meta`): `species_count`, `legal_count`, `last_synced_at`, `schema_version`.

### `TournamentRecord` (Table: `tournaments`)
- `tournament_id: str` (Primary Key, `"limitless-<id>"` or `"vr-<slug>"`)
- `name: str` (Indexed)
- `event_date: datetime` (Indexed)
- `format_regulation: str` (Indexed, e.g. `"Regulation M-A"`)
- `game_platform: str` (Indexed, `"Pokémon Champions"` or `"Scarlet & Violet"`)
- `organizer: str`, `location: str`, `total_players: int`
- `source_url: str | None`
- `standings_synced: bool` (Indexed; False = standings still to be fetched, the sync backlog)
- `event_tier: str` (Indexed; `worlds` / `international` / `regional` / `special` / `community`)
- `created_at`, `updated_at: datetime`

### `TournamentTeamRecord` (Table: `tournament_teams`)
- `tournament_team_id: UUID` (Primary Key, Indexed)
- `tournament_id: str` (Foreign Key -> `tournaments.tournament_id`, Indexed)
- `player_name: str` (Indexed)
- `placement: int` (Indexed), `standing_label: str`
- `pokepast_url: str | None`
- `showdown_text: str` (the full sheet; parsed lazily by the UI)
- `source_dataset: str`, `sync_source: str` (Indexed), `division: str` (Indexed; only `masters` is ingested)
- `member_count: int` (roster size, so the Box filter compares against it without grouping every roster row)
- `created_at: datetime`

### `TournamentTeamMemberRecord` (Table: `tournament_team_members`)
- `id: UUID` (Primary Key)
- `tournament_team_id: UUID` (Foreign Key -> `tournament_teams.tournament_team_id`, Indexed)
- `slot_position: int`
- `canonical_id: str` (Indexed), `species_name: str` (Indexed)
- `moves: list[str]` (JSON array; aggregated per species for the move picker's usage ranking)
- `base_canonical_id: str` (Indexed; Mega-stripped species id, e.g. `charizard` for `charizard-mega-y`, used to match rosters against the box)

### `MoveRecord` (Table: `moves`)
- `move_id: str` (Primary Key; Showdown id such as `"fakeout"`)
- `name: str` (Indexed)
- `type: str | None`, `category: str | None`
- `power: int | None`, `accuracy: int | None`, `pp: int | None`
- `priority: int` (default 0)
- `target: str | None`, `short_desc: str | None`
- `is_legal: bool` (Indexed; False for moves Champions removed)
- `mechanics: dict[str, Any]` (JSON): Damage-formula fields beyond power/type/category, stored as non-default keys only and read back as `domain.moves.MoveMechanics`: contact/sound/punch/bite/bullet/pulse/slicing/wind flags, `secondaries`, `recoil`, `drain`, `multihit`, `multiaccuracy`, `will_crit`, `ignore_defensive`, `override_offensive_stat`, `override_defensive_stat`, `override_offensive_pokemon`, `breaks_protect`, `has_crash_damage`, `struggle_recoil`, `mind_blown_recoil`, `self_boosts`, `ohko`.

### `LearnsetRecord` (Table: `learnsets`)
- `species_key: str` + `move_id: str` (composite Primary Key; Showdown species key, base form for megas)

### `MoveCatalogMetaRecord` (Table: `move_catalog_meta`)
- Singleton: `move_count`, `learnset_count`, `species_count`, `last_synced_at`, `schema_version` (bumped to trigger re-sync on structure changes)

### `ItemRecord` (Table: `item_records`)
- `canonical_id: str` (Primary Key, Indexed)
- `display_name: str`
- `category: str` (Indexed)
- `is_champions_legal: bool` (Indexed)
- `sprite_url: str | None`
- `short_effect: str`
- `target_species: str | None` (Indexed)
- `target_form: str | None`
- `stat_modifiers: dict[str, float]` (Stored as JSON object, e.g. `{"speed": 1.5}`)
- `created_at: datetime`, `updated_at: datetime`

### `ItemCatalogMetaRecord` (Table: `item_catalog_meta`)
- Singleton row: `id: int` (Primary Key), `total_holdable_items: int`, `last_synced_at: datetime`

### `AppStateRecord` (Table: `app_state`)
- Key/value store for sync bookkeeping: `key: str` (Primary Key), `value: str`, `updated_at: datetime`

### `TournamentSeedMetaRecord` (Table: `tournament_seed_meta`)
- Tracks tournament seed dataset loading: `id: int` (Primary Key), `seed_version: str`, `total_tournaments: int`, `total_teams: int`, `loaded_at: datetime`

---

## Derived Values

The following values are computed dynamically by the application layer rather than stored:
- **Total Stats**: Derived at runtime in both `Pokemon` and `PokemonStats` using `@computed_field`.
- **Team Stat Totals**: Summed across all active team members during a `team show` command.
- **CSV Rows**: Formatted and exported dynamically by mapping database entities to CSV rows in `csv_operations.py`.

## Naming and Identity Rules
- **Stable Identity**: The `canonical_id` is derived using `format_api_name` (e.g. `"Mega Lucario"` -> `"lucario-mega"`). This canonical name represents the database primary key for a Pokemon record, preventing duplicates caused by differences in spelling, spacing, or capitalization.
- **Friendly Display**: The display name is generated via `format_display_name` (e.g. `"lucario-mega"` -> `"Mega Lucario"`), isolating user presentation from database keys.
