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

- Pokemon box management with tags, favorites, and detailed stat inspection.
- Team creation, editing, Champions stat-point spread customization, and Showdown/Poképaste integration.
- Pokemon stat lookup from PokéAPI and Showdown catalogue synchronization (species, moves, learnsets).
- Tournament Meta analytics, standings ingestion from Limitless and Victory Road, and 1-click roster imports.
- Pokémon Champions damage calculator (roll-by-roll calculations, field conditions, status-move effects, and opponent sweep classification).
- Sorting, filtering, and advanced stat visualization.
- CSV export (full and filtered).
- Damage multiplier breakdowns by attacking type and defensive typing.
- Portable standalone executable packaging (native host PyInstaller builds and Docker + Wine Windows cross-compilation).

## Out of Scope for the First Release

- Online multiplayer features.
- Authentication and cloud sync.
- Competitive ladder tracking.
- Full battle simulation.
- Non-Pokemon-Champions game modes unless they help the same planning workflow.

## Current State

The codebase is a layered Python application (domain, services, infrastructure, Flet UI) with a local SQLite database via SQLModel. The GUI provides five full sections: Box roster, Team builder, Tournament Meta explorer, Champions damage calculator, and Settings. Data synchronizations from PokéAPI, Pokémon Showdown, Limitless VGC, and Victory Road feed the local catalogues. Standalone executable packaging is supported natively and via a Docker-based Windows cross-compilation pipeline. See the roadmap for details.

## Suggested Product Direction

A practical build order is:

1. Box first: add, view, sort, filter, and export Pokemon.
2. Team builder second: create teams, assign Pokemon, edit moves and items.
3. Insight layer third: coverage, weakness summary, and advanced stat views.
4. Polishing layer last: saved layouts, richer visual design, and workflow shortcuts.
