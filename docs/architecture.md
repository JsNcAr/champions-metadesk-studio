# Architecture & Component Notes

## Implemented Architecture

The application is structured into a clean **3-Layer Architecture** (UI, Services/Domain, Infrastructure):

```text
                  +-----------------------------------+
                  |      UI Layer (Flet Web/Desktop)  |
                  |  - Box Roster View               |
                  |  - Team Builder View             |
                  |  - Tournament Explorer View      |
                  |  - Damage Calculator View        |
                  |  - Settings View                 |
                  +-----------------+-----------------+
                                    |
                                    v
                  +-----------------------------------+
                  |           Service Layer           |
                  |  - PokemonImportService           |
                  |  - TournamentService & Synergy    |
                  |  - DamageCalcService              |
                  |  - ItemsCatalogService            |
                  |  - MoveCatalogService             |
                  |  - SpeciesCatalogService          |
                  |  - TournamentSyncService          |
                  |  - ShowdownService                |
                  +-----------------+-----------------+
                                    |
            +-----------------------+-----------------------+
            |                                               |
            v                                               v
+-----------------------+                       +-----------------------+
|     Domain Layer      |                       | Infrastructure Layer  |
| - Pokemon Identity    |                       | - SQLModel DB Repos   |
| - Item Effects        |                       | - Limitless Provider  |
| - Champions Stat Calc |                       | - Victory Road Scraper|
| - Damage Engine       |                       | - Showdown Providers  |
| - Team Validation     |                       | - PokéAPI Adapter     |
+-----------------------+                       +-----------------------+
```

### 1. UI Layer (`src/pokemon_champions_planning_tool/ui/`)
- Built using **Flet (`>=0.85.3,<0.86.0`)** running on `ft.run()`, Material 3, dark theme.
- Layout: a `NavigationRail` shell hosting five views, each owning its page header:
  1. **Box**: add-by-name with suggestions, one-row toolbar (filter, type/BST/stat drawer,
     favourites, mega-capable, planned, tags, sort, cards/table), cached cards or a sortable
     table, multi-select bulk bar, detail panel with forms, stats, abilities, defensive type
     matrix, notes, tags.
  2. **Teams**: team switcher and health chips, six slot cards (form/ability/Tera, item with
     guardrails and stat deltas, moves, spread, partners, notes), summary panel (averages,
     18×6 defensive grid, health), assign / item / spread / import / export dialogs.
  3. **Meta**: tournament teams as rows grouped by event with filters, paging and a
     lazily parsed sheet; Import hands the paste to the team builder.
  4. **Calc**: bi-directional damage calculator, one-click field strip (singles/doubles, weather,
     terrain, rooms, screens, hazards), team/box rail, result-bearing move cards with status
     toggles, and a right column that either classifies every species against the attacker
     (opponents sweep) or shows a rival team: saved plans and the "Current battle" entered at
     team preview, with battle reveals written back and a Team vs team grid.
  5. **Settings** (rail trailing slot): catalogue syncs with status and an About section.
- Package layout:

```text
ui/
  app.py            entry point: theme, context, catalogues, shell, views, startup sync
  context.py        AppContext: page, event bus, toast/confirm/prompt/clipboard/background helpers
  events.py         EventBus + named events for cross-view invalidation
  tasks.py          run_in_background (page.run_thread + page.run_task), Debouncer, is_mounted,
                    skip_auto_update
  dialogs.py        toast / confirm / prompt_text on page.show_dialog
  catalogs.py       Catalogs: Champions species, megas, items loaded once per session
  format.py         number/time formatting
  theme/            tokens.py (single source of colours, spacing, radii, type/stat palettes)
                    build.py (ft.Theme from tokens)
  shell/            AppShell: NavigationRail, layered view deck, view registry, shortcuts
  components/       PageHeader, SectionHeader, Panel, Sprite, TypeChip, StatBar, SpreadEditor, chips, banner…
  views/calc/       state (Flet-free, JSON round-trippable; sweep classification), store (mutations → recompute → persist; status-move effects; opponent sweep), rail (team/box), field_strip (tiles + side chips), panels (radar + editor + stages + move cards), move_card, sweep (opponents), rival_store (rival teams, Flet-free) + rivals_panel, dialogs/ (team preview and paste, Team vs team grid)
  views/<name>/     store.py (Flet-free data + mutations, one session per call),
                    view.py (controls; subscribes to its store), dialogs/
```

- Rules: no `Session` escapes a store; views never import each other (they talk through
  the bus); components mutate their own children and the owning view calls `update()`;
  only the shell calls `page.update()`; no hex colour literal outside `ui/theme`.
- Views are *isolated* Flet controls, so a page or slot update stops at the view boundary
  and never carries changes made inside a view: a view that changed updates itself (or
  the smallest control that changed). A handler that changed nothing calls
  `skip_auto_update()` (the `Debouncer` does it for every keystroke), otherwise Flet
  re-diffs the whole view after it (see *Rendering performance* below).
- Verification without a browser: `scripts/ui_smoke.py` builds the whole UI against a
  stub page and pushes every view through Flet's real diff/serialise path.

- `ui/components/layout.py` (`SplitPane`): a view's main content beside its side panel above 1024px, the panel overlaid on the right below it; the shell compacts the rail to icons and tightens page padding below 1280px and forwards every resize to every built view (`handle_resize(width, height)`) and updates each one, since views are isolated; they also recompute their grid tile heights.
- `ui/help.py`: the Help dialog (F1, Ctrl+/, the rail's "?" button) — keyboard shortcuts and the features that are not self-evident.
- `ui/views/meta/store.py` also holds the owned box species (base ids, refreshed on BOX_CHANGED) and passes them with every query, so rows carry in-box marks and the Box filter counts against them in SQL.
- `ui/preferences.py`: layout preferences (box layout and stats-on-cards, team summary panel and show-all-moves, meta layout and collapsed state) in `preferences.json` next to the database; in-memory in tests.
- `ui/catalogs.py` also holds the move catalogue (`moves_by_id`, `learnsets`) with `move_legality()` used by the slot cards, the health checks, the move picker and the import preview.

#### View switching (`ui/shell/shell.py`)
- Every registered view gets a full-size slot in one `Stack` (the *deck*) at
  registration, so the deck's child list never changes after mount; changing it would
  make Flet walk every slot.
- The first view (Box) is the base layer; the others are opaque overlays above it. A
  switch updates only the rail and the one or two slots involved. The higher of the two
  views crossfades (`Motion.FAST_MS`, ease-out), in or out.
- Once shown, a view stays built on the client. A hidden overlay sits at opacity 0 with
  `ignore_interactions` and `disabled`, and the base is `disabled` while covered, so
  neither clicks nor keyboard focus (Tab) reach a view that is not on screen. Hiding
  with `visible=False` is avoided on purpose: it drops the client widget tree, and
  showing the view again rebuilds it.
- Views not built yet are built during idle time after launch (`_prewarm_views` in
  `app.py`, which yields between views), mounted hidden and activated. A click that beats
  the prewarm shows a 2 px progress bar and builds on the next tick.

#### Rendering performance
- Every `update()` makes Flet diff each node under the updated control, about 30 µs per
  node. A full Box is ~9,000 controls, roughly 0.4 s per update, so update the smallest
  control that changed.
- Flet updates the nearest isolated ancestor automatically after any event handler that
  did not call `update()` itself. For keystroke and key events that change nothing, call
  `skip_auto_update()`. Plain `ft.context.disable_auto_update()` outside an event
  would switch it off for the whole process.
- Assign shared or unchanged objects to properties (borders, frames): a newly built
  nested object is sent as a replacement even when equal.
- The Box draws its first fill in chunks (`_FIRST_CHUNK`/`_NEXT_CHUNK`, 40 cards per
  tick) behind a skeleton; later renders reuse cached cards and table rows.
- Constructing a control never touches the network or the database; slow work goes
  through `run_in_background`.
- `StubPage.update()` in the tests is a no-op, so the unit suite cannot see update costs.
  Measure those against the running web app (see testing-strategy.md).

### 2. Service & Domain Layer (`src/pokemon_champions_planning_tool/services/` & `domain/`)
- Pure Python domain rules independent of UI widgets or HTTP APIs.
- Handles species identity normalization (`format_api_name`, `format_display_name`), canonical sprite resolution (`get_pokemon_sprite_url`), held item stat modifier logic, Champions stat-point calculations (`domain/stat_calc.py`: `champions_stats`, `validate_points`, `points_from_evs`), and co-occurrence synergy scoring. `domain/damage/` is the Champions damage engine (a port of the Smogon calculator's Champions module: working state, JS-faithful maths, mechanics, KO chance, descriptions); `domain/species.py` the species catalogue types and Showdown-id rules; `services/damage_calc_service.py` builds engine inputs from team slots and rosters and runs matchups.

### 3. Infrastructure & Provider Layer (`src/pokemon_champions_planning_tool/infrastructure/`)
- **Persistence**: SQLite database (`pokemon_champions.db`) managed via SQLModel repository abstractions. WAL journaling and a 64 MiB page cache. Schema migrations run only when `PRAGMA user_version` is behind `CURRENT_SCHEMA_VERSION`, so an up-to-date database starts without them.
- **Sprite cache** (`services/sprite_cache_service.py`): sprites are downloaded to `assets/sprites` in the background and served same-origin from `/sprites/`. The web build cannot load CDN sprites at all under Flet's `Cross-Origin-Embedder-Policy: require-corp`. Only files present at launch are served from disk; newer ones load from the CDN until the next launch. The assets path is absolute (`config.DEFAULT_ASSETS_DIR`) because Flet resolves a relative `assets_dir` against `sys.argv[0]`, not the working directory.
- **HTTP**: every outbound call uses the `requests` library; each provider translates
  transport failures into its own domain exception type.
- **External Providers**:
  - `PokeAPIAdapter`: Fetches official species stats, types, abilities, and sprites.
  - `LimitlessProvider`: Fetches tournament listings and standings from `play.limitlesstcg.com/api` with exponential backoff on HTTP 429 errors.
  - `VictoryRoadProvider`: Scrapes event team sheets from `victoryroad.pro` using stdlib `re` patterns, custom headers, and 25s HTTP timeouts.
- **Background Auto-Sync**: A module-level thread-safe singleton lock (`_global_sync_lock` in `app.py`) triggers a single background sync pass on startup without blocking UI initialization.

### Domain Layer

This layer contains the core rules of the app.

- Pokemon identity and form normalization
- box entry rules
- team rules
- stat aggregation
- damage multiplier logic
- coverage calculation

This layer should be independent from the GUI framework and from the way data is stored.

### Data and Integration Layer

This layer is responsible for talking to external systems and reading or writing local storage.

- local persistence for box and team data in SQLite
- cached PokéAPI responses
- CSV export generation
- PokéAPI client

## Python Project Structure

```text
src/pokemon_champions_planning_tool/
  __init__.py
  main.py
  ui/
    __init__.py
    ...
  domain/
    __init__.py
    ...
  services/
    __init__.py
    ...
  infrastructure/
    __init__.py
    ...
```

- `ui/` contains screens, widgets, and view models.
- `domain/` contains pure business logic and data rules.
- `services/` coordinates workflows such as adding a Pokemon or building a team.
- `infrastructure/` contains API clients, persistence, and CSV export helpers.

The repository is fully implemented using these package layers. The Flet GUI in `ui/`
is the primary interface; the interactive terminal shell in `services/terminal_shell.py`
remains as a secondary, still-supported entry point behind the `--cli` flag. Both drive the
same services and repositories, so neither requires database or domain changes.

## Recommended Boundaries

- The UI calls services, not PokéAPI directly.
- Services call domain logic and infrastructure helpers.
- Domain objects should not know about CSV files, HTTP requests, or GUI widgets.
- External data should be converted into internal app models at the boundary.
- Shared rules like canonical naming should exist in one place only.

## Recommended Data Flow

1. User enters a Pokemon name in the UI.
2. The UI sends the request to a service.
3. The service normalizes the name and asks the PokéAPI client for data.
4. The service converts the response into internal models.
5. The persistence layer stores or updates the box entry.
6. The UI reloads the updated box or team view.
7. CSV export uses the same internal models instead of recomputing from raw API data.

## Design Principles

- Keep the codebase small and explicit.
- Prefer plain Python classes, dataclasses, and functions over deep framework abstraction.
- Keep validation close to the domain rules.
- Make the API client and storage layer replaceable.
- Use computed summaries for coverage and totals instead of storing duplicates.
- Keep display names separate from stable internal identifiers.

## Practical Implementation Notes

- The application uses `requests`, SQLModel, SQLite, Flet, and CSV export.
- The service layer (`pokemon_import_service.py`, `terminal_shell.py`) orchestrates business flows and persistence transitions.
- SQLite is the source of truth for stored box and team data, while the CSV is kept in sync as a derived export file.

## What This Avoids

- No microservice architecture.
- No unnecessary framework-heavy dependency injection.
- No over-abstracted class hierarchy.
- No duplicated business logic across the UI and data layers.
