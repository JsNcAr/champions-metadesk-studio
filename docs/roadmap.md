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

## Phase 6: UI Overhaul [COMPLETED — 2026-09-01]
- New `ui/` package replacing the single-function GUI: navigation rail shell, per-view stores (Flet-free, one session per call), event bus, background-task helper, dialog helpers, design tokens (dark theme, per-section accents), and a component library.
- **Box**: filterable card grid and stat table, inline filter drawer (types, BST and per-stat range sliders), sort by any stat, detail panel with defensive multipliers, multi-select bulk bar (favourite, tag, delete), Undo toasts for reversible deletes, explicit CSV export.
- **Team builder**: six restyled slot cards, form / ability / Tera selectors, item picker with guardrails and stat deltas, spread editor, slot swap and reorder (menu and drag-and-drop), summary panel with averages, health checks and the defensive coverage grid, stepped Showdown import (paste → preview → readiness → done) and export / publish dialogs.
- **Meta explorer**: event-grouped rows (winner only until expanded, per event or all), a card layout with a standings dialog per event, official vs community source filter with an official tier filter (Worlds, Internationals, Regionals, Special Events), stable paging.
- **Settings** as a page with per-source sync rows and live sync progress.
- Verified with headless serialisation, a layout lint, and desktop-client screenshots under a virtual display.

## Phase 7: Data Quality & Moves [COMPLETED — 2026-09-02]
- **Tournament sync budget**: incremental listing, rate-budgeted standings fetches, retry only on retryable errors, unfinished events retried, Victory Road pages fetched once, partial events resumed, a launch-time throttle, WAL journaling and batched writes.
- **Event tiers**: tournaments classified as official (Worlds / International / Regional / Special Event) or community, stored and backfilled.
- **Move catalogue**: Pokémon Showdown's Champions learnsets, move data and Champions move changes synced into local tables; per-species move usage aggregated from stored rosters.
- **Move picker**: legal moves per species (megas use the base form), ranked by tournament usage, illegal moves hidden unless "Show all moves" is on, warnings on cards, in the health checks and in the import preview.
- **Persisted view preferences**: box layout and stats-on-cards, team summary panel and show-all-moves, meta layout and collapsed state.

## Phase 8: Insight & Workflow Backlog [COMPLETED — 2026-09-02]
- **Offensive coverage (FR-12)**: per-slot "Hits SE" row and a team-level attacking grid with uncovered types and health chips.
- **Bulk "Add to team"** from the Box selection bar and the detail panel, with "New team…".
- **Extra table columns (FR-6)**: Abilities, Dex #, Added, Notes, remembered in preferences.
- **Filtered CSV export (FR-7)**: visible or selected entries.
- **Compare teams (FR-13)**: side-by-side rosters, averages, health, coverage and shared weaknesses.
- **Saved filter views** in the Box toolbar.
- **Configurable database path** (`PCPT_DATABASE`, `PCPT_PREFERENCES`).
- **Official event discovery**: Victory Road's season calendars seed Regionals, Internationals, Worlds and Special Events automatically; finished events are read a few per run with a configurable placement cap.
- **Narrow-window layout (QR-3)**: compact icon rail below 1280px, side panels overlay the content below 1024px, grids keep their card heights.
- **Help dialog** (F1 / Ctrl+/ / rail button): shortcuts and non-obvious features.

## Phase 9: Build From Your Box [COMPLETED — 2026-09-02]
- **Box filter in the Meta explorer (FR-14)**: teams with all members in the box, or at most one, two or three missing; per-row "N/6 in box" chip and greyed missing sprites, in rows, cards and the standings dialog; updates when the box changes.
- **Data**: `base_canonical_id` on roster rows (Megas → base species, forms kept), indexed, so the match is an `IN()` per query.

## Phase 10: Champions Stat Points & Damage Calculator [COMPLETED — 2026-09-02]
- **Stat points replace EVs/IVs (FR-11a)**: Champions rules (0–32 per stat, 66 total, level 50, 31 IVs) in the domain formula, the spread editor (shared `SpreadEditor` component with presets and "Min speed"), team health checks, Showdown import (legacy EV lines converted and flagged) and export; stored spreads backfilled with `(EV + 4) // 8`.
- **Damage engine** (`domain/damage/`): a Python port of the Smogon calculator's Pokémon Champions module (MIT, see `NOTICE.md`), replayed against 997 golden scenarios generated from the calculator itself (`scripts/damage_fixtures/`).
- **Data**: move mechanics (flags, secondaries, recoil, multihit, stat overrides…) persisted on the move catalogue, with the Past-move legality fix; a Showdown species catalogue (base stats, abilities, weights, forms, Champions legality) synced like the moves.
- **Calc section (FR-15)**: team/box rail | field strip of one-click tiles over the attacker and defender panels (radar chart, stat-point editor, +/− stages, status chips, type-coloured move cards carrying the results with Activate toggles for status moves) | opponent sweep classifying every species (Crushed / Threat / Wall / Mitigated / Neutral) with tournament sets; entry points from a team slot's menu, a Meta team ("Damage calc vs…") and the Box detail panel; the last calculation remembered.

## Phase 11: Packaging & Cross-Compilation Pipeline [COMPLETED — 2026-09-04]
- **PyInstaller specification (`pokemon_champions.spec`)**: configured with dynamic imports and data hooks for SQLModel, SQLAlchemy, and Flet Desktop (`flet-desktop` runtime included) to package single-file standalone desktop executables.
- **Docker + Wine Windows cross-compilation (`scripts/build_windows_docker.sh`, `Dockerfile.windows`)**: automated container pipeline building native Windows `.exe` binaries from Linux hosts without local Wine setup, using offline wheel pre-resolution to circumvent Wine network socket constraints.
- **Dedicated build guide (`docs/building.md`)**: instructions and best practices for host native builds and cross-compilation outputs.

## Remaining Backlog
- **Offline sprite caching**: sprites are fetched from the Showdown CDN on demand (Flutter's in-memory cache covers a session).
- **Battle-log parser** (Showdown `.log` files) — integration backlog, unspecified.
