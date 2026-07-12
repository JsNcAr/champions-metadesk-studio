# Pokemon Champions Planning Tool

This repository currently contains a small Python CLI prototype for collecting Pokemon stats from PokéAPI and saving them into a local SQLite database through SQLModel, with CSV kept as a transitional export path. The long-term goal is a GUI tool for managing a Pokemon Champions box and teams.

## Current State

The codebase is intentionally small and early-stage.

- Main entry point: [src/pokemon_champions_planning_tool/main.py](src/pokemon_champions_planning_tool/main.py)
- Packaging: Poetry-based project in [pyproject.toml](pyproject.toml)
- Python version: `>=3.13`
- Runtime dependencies: `requests`, `pydantic`, `sqlmodel`
- Primary local storage: `pokemon_champions.db` in the repository root
- CSV export: `pokemon_team_stats.csv` in the repository root
- GUI status: not implemented yet
- Tests: Automated unit and repository integration tests cover name normalization and database operations.

## What The Prototype Does

- Launches an interactive command shell for Pokemon box and team management.
- Normalizes Pokemon names (e.g. regional variants and Mega forms) before querying PokéAPI.
- Fetches official base stats, types, abilities, and sprites from PokéAPI.
- Persists Pokemon records, box entries, and team structures locally in SQLite via SQLModel.
- Synchronizes the box state to `pokemon_team_stats.csv` automatically when changes occur.
- Exposes terminal commands to add, inspect, delete, note, tag, and favorite box entries.
- Supports team creation, slot assignment (with item, moveset, and ability configuration), and team list/show commands.

## Planned Product

The target product is a GUI tool for:

- managing a Pokemon box
- building and editing multiple teams
- viewing stats, abilities, moves, typing, and coverage
- sorting and filtering box entries
- viewing and exporting data from the local SQLite-backed box
- exporting data to CSV for external analysis

The product planning documents live in [docs/README.md](docs/README.md).

## Running The CLI

```bash
poetry install
PYTHONPATH=src poetry run python -m pokemon_champions_planning_tool.main
```

Example session:

```text
========================================================
  Pokemon Champions Box & Team Terminal  
========================================================
Type 'help' to see commands, or 'exit' to close.

pokemon> add Pikachu
🔍 Querying PokéAPI endpoint for 'Pikachu'...
✅ Success: Saved 'Pikachu' to SQLite and CSV.

pokemon> box list
Pokemon | Form | Types    | Total | Fav
--------+------+----------+-------+----
Pikachu | Base | electric | 320   | no 

pokemon> box favorite Pikachu on
✅ Favorite status updated for 'Pikachu'.

pokemon> team create "Electric Storm"
✅ Created team 'Electric Storm'.

pokemon> team add "Electric Storm" 1 Pikachu --item "Light Ball" --ability "Static" --notes "Lead sweeper"
✅ Added 'Pikachu' to team 'Electric Storm' in slot 1.

pokemon> team show "Electric Storm"
Team: Electric Storm
ID: d079234b-4860-4966-8968-3e4cb418df4f
Description: None
Slot | Pokemon | Item       | Ability | Moves | Total
-----+---------+------------+---------+-------+------
1    | Pikachu | Light Ball | Static  | -     | 320  
Team totals: HP 35 | Atk 55 | Def 40 | SpA 50 | SpD 50 | Spe 90

pokemon> exit
Shutting down data pipeline...
```

## Running Tests

To run the automated unit and integration tests:

```bash
PYTHONPATH=src poetry run python -m unittest discover -s tests
```

## Repository Layout

```text
pokemon_champions.db          # Local SQLite Database
pokemon_team_stats.csv        # Transitional CSV Export
pyproject.toml                # Poetry configuration
README.md                     # Root project documentation
docs/                         # Detailed design and vision documents
src/                          # Main source directory
    pokemon_champions_planning_tool/
        main.py               # Application entry point
        config.py             # Global configurations & constants
        domain/               # Core business entities & domain logic
        infrastructure/       # PokéAPI client, database schemas, and CSV operations
        services/             # Orchestrating workflows and interactive shell CLI
        ui/                   # UI placeholder for future GUI
tests/                        # Automated unit & integration tests
```

## Notes

- The interactive CLI serves as a fully functional domain, service, and persistence prototype.
- The package structure under `src/pokemon_champions_planning_tool/` implements a clean 3-layer architecture (UI, Domain, Infrastructure) to support the eventual GUI transition.
- SQLite is the source of truth for all stored box and team data, while CSV remains a derived export-friendly snapshot.
