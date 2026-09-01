# Pokemon Champions Planning Tool

The **Pokemon Champions Planning Tool** is a feature-rich desktop and web planning application for competitive Pokémon VGC and Champions format players. Built with Python, Flet, SQLModel, and SQLite, it offers box roster management, team building, Poképaste/Showdown competitive imports, and live tournament meta analytics with automated background synchronization from external sources like Limitless VGC and Victory Road.

## Current State

The project is fully functional as a modern **Flet Web/Desktop GUI** and interactive CLI shell.

- **Main Entry Point**: [src/pokemon_champions_planning_tool/main.py](src/pokemon_champions_planning_tool/main.py)
- **GUI Engine**: Flet (`>=0.80.0`) running on `ft.run()` with web support.
- **Packaging & Environment**: Poetry-based project in [pyproject.toml](pyproject.toml) (Python `>=3.13`)
- **Primary Database**: `pokemon_champions.db` (SQLite managed via SQLModel)
- **Transitional Data Exports**: `pokemon_team_stats.csv` automatically synchronized with box state
- **Test Suite**: Automated unit and integration test suite (**68 passing tests**)

## Key Features

### 📦 1. Box Roster Management
- **PokéAPI Integration**: Add species by name with automatic normalization for Mega forms and regional variants.
- **Advanced Filtering**: Filter by 17 type pills, ★ Favorites, ⚡ Mega-Capable status, and custom tag chips.
- **Details Drawer**: Inspect base stats, types, abilities, notes, and tags in an interactive panel.
- **CSV Snapshot Export**: Export box data to CSV for external spreadsheet analysis.

### ⚔️ 2. Team Builder & Competitive Spreads
- **Multi-Team Squads**: Create, rename, switch, and delete competitive teams.
- **Visual Roster Banner**: 6-slot preview rings with real-time stat progress bars and Mega indicator badges.
- **Hero Slot Cards**: Auto-saving form/ability selectors, 4-slot move fields, and held item picker with Champions format legality guardrails.
- **Stat Modifier Badges**: Automatic delta display (+50% Atk/SpA/SpD/Spe) when Choice items or Assault Vest are equipped.
- **EV/IV Spread Editor**: Nature selector, level input, EV sliders/presets, and IV presets (e.g. 0 Speed TR, 0 Atk).
- **Showdown & Poképaste Integration**: 1-click text export/import and direct publishing to Pokepast.es.
- **Planned Pokémon (Ghost Entries)**: Store non-owned Pokémon templates (`is_planned=True`) without cluttering the Box roster.

### 🏆 3. Tournament Explorer & Meta Analytics
- **Live Tournament Sync**: Background thread automatically fetches official standings and team sheets from **Limitless VGC API** and **Victory Road**.
- **Rate-Limit & Robust Retries**: Implements exponential backoff on HTTP 429 rate limits and 25s timeouts for heavy event pages.
- **Search & Filtering**: Search tournament teams by contained species, player name, tournament title, regulation format, and placement.
- **1-Click Roster Import**: Instantly copy any winning 6-Pokémon tournament team directly into your active Team Builder slots.
- **Teammate Synergy Analytics**: Surfaces top co-occurring partner recommendations based on tournament usage data.

---

## Running The Application

### Running The GUI

To launch the Flet GUI in your web browser:

```bash
PYTHONPATH=src poetry run python -m pokemon_champions_planning_tool.main --web
```

The app will open automatically at `http://localhost:8550`.

#### Stopping an Active Server / Port Conflict

If port `8550` is already in use by a background process:

```bash
# Kill process using port 8550:
fuser -k 8550/tcp

# Or kill by module name:
pkill -f "pokemon_champions_planning_tool.main"
```

### Running The Interactive CLI

```bash
PYTHONPATH=src poetry run python -m pokemon_champions_planning_tool.main
```

### Running Tests

```bash
PYTHONPATH=src poetry run python -m unittest discover -s tests
```

---

## Repository Layout

```text
pokemon_champions.db          # SQLite Database (Source of Truth)
pokemon_team_stats.csv        # Transitional CSV Export
pyproject.toml                # Poetry dependencies and configuration
README.md                     # Main documentation
docs/                         # Architecture, Data Model, Requirements, and Roadmap
src/
    pokemon_champions_planning_tool/
        main.py               # Main entry point (GUI / CLI selector)
        config.py             # Global constants & environment settings
        domain/               # Core entities & domain rules (Pokemon, Team, Identity)
        infrastructure/       # Database models, repositories, PokéAPI, Limitless & Victory Road providers
        services/             # Business orchestrators (Import, Tournament, Item Catalog, Showdown)
        ui/                   # Flet GUI views and components (app.py)
tests/                        # Automated unit & integration test suite
```
