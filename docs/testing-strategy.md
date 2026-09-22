# Testing Strategy

## Testing Goals

The project should be tested around the behaviors that matter most for planning and box management:

- Pokemon name normalization
- canonical identity handling
- PokéAPI response handling
- CSV export and update behavior
- stat sorting and filtering rules
- team coverage and stat aggregation

## Recommended Test Layers

### Unit Tests

Use unit tests for:

- name normalization
- display-name generation
- damage multiplier calculations
- the damage engine: `tests/test_damage_fixtures.py` replays ~1000 golden scenarios generated from the Smogon calculator's Champions module (`scripts/damage_fixtures/`, Node, dev-only) and must match roll for roll, in the description and the KO text; regenerate only when `CALC_COMMIT` is bumped
- stat totals
- coverage summaries

### Service Tests

Use service or integration-style tests for:

- PokéAPI adapters
- CSV persistence
- box upsert logic
- team CRUD operations

### UI Tests

The GUI is validated without requiring an interactive display:

- **Headless Component & View Tests (`tests/test_ui_*.py`)**: Using `_ui_stubs.py` (`StubPage`), views and dialogs are tested for event handling, control generation, and store interactions.
- **Whole-App Serialization Smoke Test (`scripts/ui_smoke.py`)**: Builds the shell and all five views against an actual SQLite database, verifying Flet control tree serialization and database relational integrity.
- **Performance and interaction checks against the running app**: `StubPage.update()` is a no-op, so unit tests show neither what an update costs nor what the client does with it. For rendering, focus and latency changes, run the web build (`--web`, port 8550) against a database at realistic scale and drive it with headless Chromium (Playwright). Time click-to-pixel-change and typing-to-result, and log patch sizes by wrapping Flet's `Session` patch builder. Check that nothing else holds port 8550 first, or the probe measures a stale server. Headless software rendering adds about 0.5 s to every visible change, so compare before/after runs on the same machine rather than reading absolute numbers.

## Priority Test Cases

1. The same Pokemon added with different naming styles maps to one canonical entry.
2. Re-adding an existing Pokemon updates the row rather than duplicating it.
3. Filtering by stat range, tags, or Mega status returns only matching Pokemon.
4. Team stat totals and offensive/defensive coverage update dynamically as members change.
5. Stat points validate against the Champions 66-point budget, and Showdown pastes convert legacy EVs correctly.
6. The Champions damage calculator reproduces roll-by-roll damage and KO text matching the Smogon calculator.
7. Tournament syncing adheres to rate budgets and resumes partial event standings correctly.

## Tooling and Execution

The project uses Python's standard `unittest` library for automated test execution to avoid external test runner dependencies.

### Running Automated Tests
```bash
poetry run python -m unittest discover -s tests
```
The test suite executes **590 automated unit, service, repository, and UI tests** using temporary in-memory/isolated SQLite databases.

### Running Headless UI Smoke Test
```bash
poetry run python scripts/ui_smoke.py --db pokemon_champions.db
```
Serializes all 5 views (Box, Teams, Meta, Calc, Settings) through Flet's control diff pipeline and checks database foreign-key integrity.
