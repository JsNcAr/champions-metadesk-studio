# Architecture Notes

## Current Architecture

The repository currently has a single Python CLI entry point that:

- accepts a Pokemon name from the terminal
- normalizes it into a PokéAPI identifier
- fetches official stats from PokéAPI
- writes or updates a CSV row in the repository root

This is a useful prototype, but it is not yet the target GUI architecture.

## Target Architecture

The GUI should stay simple, testable, and easy to extend. A practical fit for this project is a small Python application with three clear layers.

### UI Layer

This layer handles rendering and user interaction only.

- box viewer
- Pokemon detail view
- team builder view
- filters, sorting, and export controls
- advanced visualization panels

The UI should not contain business rules or direct API calls.

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

- local persistence for box and team data
- cached PokéAPI responses
- CSV export generation
- PokéAPI client

## Suggested Python Project Structure

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

The repository now includes these package folders as a lightweight scaffold, so the future GUI work can grow into the intended structure without a major rewrite.

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

- The current prototype uses `requests` and direct CSV writes.
- The next refactor should introduce a service layer before the GUI is built.
- A lightweight persistence approach is enough at first, such as JSON, SQLite, or another simple local store.
- Start with the minimum structure that keeps the box, team, and export logic independent.

## What This Avoids

- No microservice architecture.
- No unnecessary framework-heavy dependency injection.
- No over-abstracted class hierarchy.
- No duplicated business logic across the UI and data layers.
