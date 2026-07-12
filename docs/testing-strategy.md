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
- stat totals
- coverage summaries

### Service Tests

Use service or integration-style tests for:

- PokéAPI adapters
- CSV persistence
- box upsert logic
- team CRUD operations

### UI Tests

When the GUI exists, cover:

- adding a Pokemon from the box screen
- selecting a Pokemon for details
- applying filters and sort options
- editing team members and movesets
- viewing coverage and total stat summaries

## Priority Test Cases

1. The same Pokemon added with different naming styles should map to one canonical entry.
2. Re-adding an existing Pokemon should update the row rather than duplicate it.
3. Filtering by stat range should return only matching Pokemon.
4. Team stat totals should equal the sum of all team members.
5. Type coverage should classify attacking and defensive multipliers correctly.

## Suggested Tooling and Execution

The project uses Python's standard `unittest` library for test runner execution to avoid adding external dependencies. 

To run the automated tests:
```bash
PYTHONPATH=src poetry run python -m unittest discover -s tests
```

- `unittest.TestCase` is used for unit and database integration tests.
- SQLite is tested using temporary folder paths for in-memory/isolated SQLite engines.
- Future work: Mock PokéAPI responses to keep tests stable and fast.
- Future work: Introduce a GUI testing framework later, depending on the chosen frontend.
