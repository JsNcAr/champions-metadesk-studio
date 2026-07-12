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

The repository currently has a CLI prototype that queries PokéAPI, stores the current box state in SQLite via SQLModel, exports the current box to CSV, and exposes basic box/team terminal commands. The planned GUI, richer filtering, and visualization features are documented here but not implemented yet.

## Recommended Reading Order

1. Start with [Project Vision and Scope](vision-scope.md).
2. Read [Functional Requirements](functional-requirements.md) and [User Stories](user-stories.md).
3. Review [Architecture Notes](architecture.md) and [Data Model](data-model.md).
4. Use [Product Roadmap](roadmap.md) to understand the build sequence.
