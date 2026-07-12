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
- Tests: no automated project tests yet

## What The Prototype Does

- Prompts for a Pokemon name in the terminal.
- Normalizes a few common naming patterns before calling PokéAPI.
- Fetches the Pokemon's official stats from PokéAPI.
- Upserts the Pokemon into the SQLite database using a canonical identity.
- Mirrors the current box state to `pokemon_team_stats.csv` as a transitional export.
- Keeps running until you type `exit` or `quit`.

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
python -m pokemon_champions_planning_tool.main
```

Example session:

```text
Enter Pokemon Name: Pikachu
Enter Pokemon Name: Mega Lucario
Enter Pokemon Name: exit
```

## Repository Layout

```text
pokemon_team_stats.csv
pyproject.toml
README.md
docs/
src/
	pokemon_champions_planning_tool/
		main.py
		domain/
		infrastructure/
		services/
		ui/
tests/
```

## Notes

- The CLI is a prototype, not the final architecture.
- The new package folders under `src/pokemon_champions_planning_tool/` are a lightweight scaffold for the future GUI.
- SQLite is the current source of truth for stored box data, while CSV remains an export-friendly transitional format.
