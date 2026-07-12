# Integration Notes

## PokéAPI

PokéAPI is the main external data source for the project.

### Expected Uses

- Pokemon base data
- Forms and variants
- Types
- Stats
- Abilities
- Moves
- Sprites

### Integration Concerns

- Network failures must be handled gracefully.
- API naming rules must be normalized consistently.
- Repeated calls should eventually be cached.
- The app should tolerate partial data when some endpoints are unavailable.

## CSV Export

CSV remains a useful export format because it is simple and compatible with spreadsheets.

### Export Goals

- easy external analysis
- simple import into spreadsheet tools
- stable column order
- no loss of core stats data

## Future Integrations

Optional later integrations could include:

- local sqlite file configuration (allowing custom database file paths)
- image and sprite offline caching (to prevent redownloading from PokéAPI)
- import from external team planning tools, exportable JSON formats, or team worksheets
- battle data sources if the project expands beyond planning (e.g. Smogon usage statistics)
