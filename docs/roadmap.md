# Product Roadmap

## Phase 0: CLI Prototype [COMPLETED]
- CLI-based PokéAPI lookup.
- SQLite-backed box persistence through SQLModel.
- CSV export of the current box snapshot.
- Terminal commands for box and team management.
- Basic name normalization for regional/mega forms.
- Duplicate handling via canonical PokéAPI identity.

## Phase 1: Core Data Layer [COMPLETED]
- SQLite consolidated as the source of truth using SQLModel schemas.
- Defined domain entities and database records for:
  - `Pokemon` and `PokemonStats`
  - `PokemonAbility` and `PokemonMove`
  - `PokemonForm`
  - `BoxEntry` (with notes, tags, favorite state)
  - `Team` and `TeamMember` (referencing box entries)
- Created full Repository CRUD patterns (`BoxRepository`, `TeamRepository`, `ChampionsCatalogRepository`, `MegaEvolutionRepository`, `ItemRepository`).
- Unit test suite covering repository operations, item effects, and domain logic.

## Phase 2: Box Roster Viewer [COMPLETED]
- Modern Flet GUI Box Roster view (`app.py`).
- Card layout displaying sprites, display names, type badges, BST, and forms.
- **Advanced Filtering Toolbar**:
  - 17 Type Pills (`Fire`, `Water`, `Grass`, etc.) with type colors and `All`.
  - Quick Toggles for `★ Favorites Only` and `⚡ Mega Capable Only`.
  - Combined **AND-filtering** logic with text search.
  - One-click **Clear Filters** button.
- **Interactive Tag Chips**: Custom user tags displayed as clickable blue pills on cards; clicking a tag filters the roster instantly.
- Detail drawer panel for inspecting stats, managing tags, and editing notes.
- CSV Export toolbar button.

## Phase 3: Team Builder & Item System [COMPLETED]
- Multi-team management (Create, Switch, Delete).
- **Persistent Team Overview Banner**: 6 circular sprite preview rings with type-color borders.
- **Visual Stat Totals**: Progress bars for team total stats (`HP`, `Atk`, `Def`, `SpA`, `SpD`, `Spe`) styled with official stat palette colors.
- **Hero Slot Cards**:
  - Type-color-tinted hero headers with slot pill, sprite, display name, type badges, BST, and `⚡ MEGA` indicator.
  - Auto-save form and ability dropdown changes without manual save buttons.
  - **4-Slot Move Chip System**: 2x2 grid of move fields with auto-save on blur/submit.
  - **Multi-Stat Modifier Badges**: Equipping `Choice Band` (+50% Atk), `Choice Specs` (+50% SpA), `Choice Scarf` (+50% Spe), or `Assault Vest` (+50% SpD) displays color-coded delta badges.
- **Team Health Validation Panel**: Real-time checks for duplicate held items, Mega Stone count limits (max 1 per team), and team roster completeness (6/6 slots).
- **Item Picker Modal**: Category filters, legality badges, species-matching guardrails, and incompatible Mega Stones sorted at bottom.
- **Data & Sync Settings**: Modal for manual PokéAPI / Showdown data synchronization.

---

## Phase 4: Competitive Imports & Spreads [COMPLETED]
- **Showdown Export Workflow**: One-click generation of standard Showdown text & direct publishing to Pokepast.es with shareable URLs.
- **Showdown Import Workflow**: Parse raw text or Pokepast.es URLs into live team slots with interactive 6-slot preview grid.
- **Phase 0 Prerequisites**:
  - **Planned Pokémon / Ghost-Entry System**: `is_planned` flag on `BoxEntryRecord` allowing non-owned Pokémon to be stored as team templates without cluttering the Box roster.
  - **Readiness Orchestrator**: 3-option import modal (Add to Box, Import as Template, Cancel).
  - **EVs, IVs, Nature & Level Tracking**: Full JSON schema for competitive stat spreads on `TeamMemberRecord`.
  - **Spread Editor UI**: Interactive modal with nature selector, level input, EV sliders/presets (Phys Sweeper, Spec Sweeper, Bulky Support) and IV presets (0 Atk, 0 Spe Trick Room, 31 All).

## Phase 5: Meta & Tournament Team Explorer [COMPLETED]
- **Multi-Source Tournament Sync**: Automated background sync thread fetching official tournament rosters and standings from **Limitless VGC API** (with 429 retry backoff) and **Victory Road** HTML results parser.
- **SQLite Storage**: `TournamentRecord`, `TournamentTeamRecord`, and `TournamentTeamMemberRecord` persistence models.
- **Search & Filtering**: Search tournament teams by contained species, player name, tournament title, regulation format (Regulation M-A/M-B), recency, and standing placement.
- **1-Click Import to Team Builder**: Import any 6-Pokémon tournament roster directly into active Team Builder slots.
- **PokéPaste Integration**: Direct button to launch original Poképaste event sheets in browser.
- **Teammate Synergy Analytics**: Surfaces co-occurrence partner recommendations based on tournament usage statistics.
- **High-Reliability Sprite Rendering**: Pokemon Showdown CDN sprite resolution for all regional/special forms (Hisuian Arcanine, Floette Eternal, Urshifu forms, Mega forms).

---

## Upcoming Planned Features (Missing Backlog)

### 🛡️ Feature 1: Type Coverage & Vulnerability Matrix (Team Builder)
- **Defensive Type Matrix**: Visual chart showing team-wide weaknesses, resistances, and immunities per attacking type (e.g., *“3 members weak to Ground, 1 immunity”*).
- **Offensive STAB & Move Coverage**: Summary highlighting uncovered attacking types based on team movesets and primary types.

### 🔄 Feature 2: Quick Slot Reordering & Swapping (Team Builder)
- Reorder team slots (e.g. *"Move to Lead"*, *"Swap Slot 2 with Slot 5"*) via slot card action buttons without clearing slots.

### 🔍 Feature 3: Move Autocomplete & Move Legality Service
- Search/autocomplete move catalog service for 4-slot chips to verify move legality for chosen species and active form against PokéAPI learnsets.

### 📊 Feature 4: BST Range Slider Filter (Box Roster)
- Min/max BST range slider in the Box toolbar to filter entries by base stat total threshold (e.g., BST 500–700).

### 🏷️ Feature 5: Bulk Roster Actions (Box Roster)
- Multi-select box entries to batch-tag, batch-favorite, batch-delete, or assign to teams simultaneously.

