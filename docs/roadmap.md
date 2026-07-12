# Product Roadmap

## Phase 0: Current Prototype

- CLI-based PokéAPI lookup.
- SQLite-backed box persistence through SQLModel.
- CSV export of the current box snapshot.
- Terminal commands for box and team management.
- Basic name normalization for a few common forms.
- Duplicate handling via canonical PokéAPI identity.

## Phase 1: Core Data Layer

- Consolidate the data model around SQLite as the source of truth.
- Define entities for Pokemon, forms, stats, moves, abilities, items, box entries, and teams.
- Add full CRUD repositories for box and team data.
- Add migrations or schema bootstrap support if the schema changes.
- Keep CSV export as a derived output, not the primary store.

## Phase 2: Box Viewer

- Build the default box page.
- Display image, name, and types.
- Add search, sort, and filter controls.
- Add the detail panel for stats, abilities, and moves.

## Phase 3: Team Builder

- Add multiple team CRUD.
- Support drag-and-drop or selection-based team assignment.
- Add team member editing for items and moves.
- Show team summaries and type coverage.

## Phase 4: Advanced Analysis

- Add advanced stat visualization.
- Add defensive damage charts by attacking type.
- Add bulk export and comparison tools.
- Add quality-of-life features such as favorites, tags, and saved filters.

## Phase 5: Polish and Hardening

- Add tests for data normalization and rules.
- Add API caching to reduce repeated calls.
- Improve error handling and offline behavior.
- Review GUI accessibility and layout responsiveness.

## Easy Wins

These are low-risk additions that fit the current direction and can be added early:

- normalize and deduplicate Pokemon names more aggressively
- cache PokéAPI responses locally
- add a separate CSV export command for the current box
- add stat-based filters before the full GUI exists
- add a first-pass damage multiplier calculator from type data
