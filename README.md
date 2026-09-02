# Pokemon Champions Planning Tool

The **Pokemon Champions Planning Tool** is a feature-rich desktop and web planning application for competitive Pokémon VGC and Champions format players. Built with Python, Flet, SQLModel, and SQLite, it offers box roster management, team building, Poképaste/Showdown competitive imports, and live tournament meta analytics with automated background synchronization from external sources like Limitless VGC and Victory Road.

## Current State

The project is fully functional as a modern **Flet Web/Desktop GUI** and interactive CLI shell.

- **Main Entry Point**: [src/pokemon_champions_planning_tool/main.py](src/pokemon_champions_planning_tool/main.py)
- **GUI Engine**: Flet (`>=0.85.3,<0.86.0`) running on `ft.run()` with web support.
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
- **Stat-point spread editor**: Champions has no EVs or IVs — every Pokémon is level 50 with 31 IVs and spends 0–32 stat points per stat (66 in total). Nature selector, point sliders with a budget bar, presets and a "Min speed" chip for Trick Room. Showdown pastes with mainline 252-style EV lines are converted on import without changing any stat.
- **Showdown & Poképaste Integration**: 1-click text export/import and direct publishing to Pokepast.es.
- **Planned Pokémon (Ghost Entries)**: Store non-owned Pokémon templates (`is_planned=True`) without cluttering the Box roster.

### 🧮 4. Damage Calculator
- **Both directions at once**: each move card shows base power, the type multiplier, the damage range, a bar and the KO chance; expand it for the 16 rolls and the Smogon-style description. Status moves with a known effect have an Activate toggle.
- **One-click field**: tiles for Singles/Doubles, Tailwind per side, Trick Room, weather, terrain and rooms; chips for screens, Helping Hand, hazards, Leech Seed and Spikes per side.
- **Team rail and opponent sweep**: load a team member or box Pokémon with one click; the Opponents rail classifies every Champions species against the attacker (Crushed / Threat / Wall / Mitigated / Neutral), searchable, with each opponent's most used tournament moves.
- **Full Champions mechanics**: weather, terrain, screens, Tailwind, Helping Hand, hazards, Leech Seed, status, stat stages, current HP (Eruption, Flail, Hard Press, Multiscale…), weight (Heavy Slam, Low Kick…), abilities, held items, critical hits, doubles spread, multi-hit and Parental Bond.
- **Verified**: a Python port of the Smogon calculator's Pokémon Champions module, replayed against ~1000 golden scenarios generated from the calculator itself.
- **Entry points**: "Open in damage calc" on a team slot, "Damage calc vs…" on a Meta team (with the paste's set), "Damage calc" in the Box detail panel; the last calculation is remembered.

### 🏆 3. Tournament Explorer & Meta Analytics
- **Live Tournament Sync**: Background thread automatically fetches official standings and team sheets from **Limitless VGC API** and **Victory Road**.
- **Rate-Limit & Robust Retries**: Implements exponential backoff on HTTP 429 rate limits and 25s timeouts for heavy event pages.
- **Search & Filtering**: Search tournament teams by contained species, player name, tournament title, regulation format, and placement.
- **1-Click Roster Import**: Instantly copy any winning 6-Pokémon tournament team directly into your active Team Builder slots.
- **Teammate Synergy Analytics**: Surfaces top co-occurring partner recommendations based on tournament usage data.

---

## Running The Application

The entry point selects its interface from the command-line flag:

| Command | Interface |
| --- | --- |
| `poetry run python -m pokemon_champions_planning_tool.main` | Flet desktop app (default) |
| `poetry run python -m pokemon_champions_planning_tool.main --web` | Flet GUI in the web browser |
| `poetry run python -m pokemon_champions_planning_tool.main --cli` | Interactive terminal shell |

### Running The GUI

To launch the Flet GUI in your web browser:

```bash
poetry run python -m pokemon_champions_planning_tool.main --web
```

The app will open automatically at `http://localhost:8550`.

Without a flag, the same GUI opens as a native desktop window instead.

#### Stopping an Active Server / Port Conflict

If port `8550` is already in use by a background process:

```bash
# Kill process using port 8550:
fuser -k 8550/tcp

# Or kill by module name:
pkill -f "pokemon_champions_planning_tool.main"
```

### Running The Interactive CLI

The terminal shell requires the `--cli` flag; without it the GUI launches instead.

```bash
poetry run python -m pokemon_champions_planning_tool.main --cli
```

### Running Tests

```bash
poetry run python -m unittest discover -s tests
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

## Keyboard shortcuts

Press **F1** (or Ctrl+/) in the app for the full list with tips. The essentials: Ctrl+1/2/3/4 switch sections (Box, Teams, Meta, Calc), Ctrl+, opens Settings, Ctrl+F focuses the search, Ctrl+K adds to the box, Ctrl+N/I/E create, import and export a team, Escape closes dialogs and panels, Delete removes the selection with Undo.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PCPT_DATABASE` | `pokemon_champions.db` (working directory) | Path of the SQLite database file. |
| `PCPT_PREFERENCES` | `preferences.json` beside the database | Path of the view-preferences file. |
| `PCPT_VR_MAX_PLACEMENT` | `64` | Placements ingested per official event from Victory Road (Regionals publish hundreds of sheets). |

Example: `PCPT_DATABASE=~/pokemon/champions.db poetry run python -m pokemon_champions_planning_tool.main`
