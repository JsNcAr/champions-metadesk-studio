# Project Vision and Scope

## Vision

Build a desktop or web-based GUI tool that helps players manage a Pokemon Champions box, build teams, inspect matchups, and export structured data for analysis.

The tool should make it easy to add a Pokemon by name, review its stats and typing, organize the box, assemble multiple teams, and compare coverage and weaknesses with minimal manual data entry.

## Product Goals

- Reduce manual work when collecting Pokemon data.
- Provide a clear visual box view with searchable and sortable Pokemon entries.
- Make team building and team comparison fast and data-driven.
- Support exportable stats so users can do external analysis in CSV or spreadsheet tools.
- Present matchup and damage-type information in a way that is useful for planning.

## In Scope

- Pokemon box management.
- Team creation and editing.
- Pokemon stat lookup from PokéAPI.
- Display of image, name, typing, abilities, moves, and stat summaries.
- Sorting, filtering, and advanced stat visualization.
- CSV export.
- Damage multiplier breakdowns by attacking type and defensive typing.

## Out of Scope for the First Release

- Online multiplayer features.
- Authentication and cloud sync.
- Competitive ladder tracking.
- Full battle simulation.
- Non-Pokemon-Champions game modes unless they help the same planning workflow.

## Current State

The codebase is a layered Python application (domain, services, infrastructure, Flet UI) with a local SQLite database via SQLModel. The GUI covers the Box roster, the team builder, the tournament Meta explorer and Settings; PokéAPI, Pokémon Showdown, Limitless and Victory Road feed the local catalogues. See the roadmap for what is done and what remains.

## Suggested Product Direction

A practical build order is:

1. Box first: add, view, sort, filter, and export Pokemon.
2. Team builder second: create teams, assign Pokemon, edit moves and items.
3. Insight layer third: coverage, weakness summary, and advanced stat views.
4. Polishing layer last: saved layouts, richer visual design, and workflow shortcuts.
