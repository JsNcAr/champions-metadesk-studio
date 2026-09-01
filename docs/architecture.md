# Architecture & Component Notes

## Implemented Architecture

The application is structured into a clean **3-Layer Architecture** (UI, Services/Domain, Infrastructure):

```text
                  +-----------------------------------+
                  |      UI Layer (Flet Web/Desktop)  |
                  |  - Box Roster View               |
                  |  - Team Builder View             |
                  |  - Tournament Explorer View      |
                  +-----------------+-----------------+
                                    |
                                    v
                  +-----------------------------------+
                  |           Service Layer           |
                  |  - PokemonImportService           |
                  |  - TournamentService              |
                  |  - ItemsCatalogService            |
                  |  - ShowdownService                |
                  |  - MetaSynergyService             |
                  +-----------------+-----------------+
                                    |
            +-----------------------+-----------------------+
            |                                               |
            v                                               v
+-----------------------+                       +-----------------------+
|     Domain Layer      |                       | Infrastructure Layer  |
| - Pokemon Identity    |                       | - SQLModel DB Repos   |
| - Item Effects        |                       | - Limitless Provider  |
| - Team Validation     |                       | - Victory Road Scraper|
| - Synergy Metrics     |                       | - PokéAPI Adapter     |
+-----------------------+                       +-----------------------+
```

### 1. UI Layer (`src/pokemon_champions_planning_tool/ui/`)
- Built using **Flet (`>=0.85.3,<0.86.0`)** running on `ft.run()`.
- Implements a reactive single-page interface with 3 main view tabs:
  1. **Box Roster**: Grid view, type pills, favorites, details drawer, CSV export.
  2. **Team Builder**: 6-slot preview banner, hero slot cards, held item modal, EV/IV spread modal, Poképaste import/export.
  3. **Tournament Explorer**: Standings grid, regulation filters, roster search, 1-click import, partner synergy analytics.
- **Colour palette**: `ui/theme.py` defines a `Colors` class of explicit colour strings
  (a Tailwind-style dark slate palette plus semantic surface tokens such as `CARD_BG`,
  `PANEL_BG`, and `DIVIDER` that Material does not provide). The UI imports this palette
  directly and does **not** patch or read `ft.Colors` — an undefined token must raise
  `AttributeError` at the call site rather than resolve to an unrenderable colour name.

### 2. Service & Domain Layer (`src/pokemon_champions_planning_tool/services/` & `domain/`)
- Pure Python domain rules independent of UI widgets or HTTP APIs.
- Handles species identity normalization (`format_api_name`, `format_display_name`), canonical sprite resolution (`get_pokemon_sprite_url`), held item stat modifier logic, EV/IV spread calculations, and co-occurrence synergy scoring.

### 3. Infrastructure & Provider Layer (`src/pokemon_champions_planning_tool/infrastructure/`)
- **Persistence**: SQLite database (`pokemon_champions.db`) managed via SQLModel repository abstractions.
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

The repository is fully implemented using these package layers. The Flet GUI in `ui/app.py`
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
