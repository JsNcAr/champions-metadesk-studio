# Documentation Index

This folder contains the planning documents for the Pokemon Champions planning tool. The root [README.md](../README.md) is the project entry point for the current CLI prototype, while this folder tracks the intended GUI product and the current SQLite-backed persistence direction.

## How The Docs Fit Together

- [Project Vision and Scope](vision-scope.md) describes the product direction.
- [Functional Requirements](functional-requirements.md) defines the features the GUI should support.
- [User Stories](user-stories.md) translates those features into user-facing behavior.
- [Product Roadmap](roadmap.md) orders the work into practical phases.
- [Architecture Notes](architecture.md) explains the simple Python structure the project should follow.
- [Data Model](data-model.md) outlines the core entities.
- [Integration Notes](integrations.md) covers PokéAPI, SQLite, and export concerns.
- [Testing Strategy](testing-strategy.md) describes the validation approach.

## Current Implementation Status

The application is a Flet desktop GUI (with a CLI fallback) backed by SQLite via SQLModel: a filterable Box roster, a six-slot team builder with items, spreads, moves and Showdown import/export, a tournament Meta explorer fed by Limitless and Victory Road, a Champions damage calculator, and a Settings page for the data syncs. Phases 0–10 of the [roadmap](roadmap.md) are complete; the remaining backlog is listed there. `architecture.md` describes the current `ui/` package.

## Recommended Reading Order

1. Start with [Project Vision and Scope](vision-scope.md).
2. Read [Functional Requirements](functional-requirements.md) and [User Stories](user-stories.md).
3. Review [Architecture Notes](architecture.md) and [Data Model](data-model.md).
4. Use [Product Roadmap](roadmap.md) to understand the build sequence.
