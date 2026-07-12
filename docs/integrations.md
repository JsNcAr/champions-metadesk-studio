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

- local JSON storage for the app database
- image caching for sprites and artwork
- import from external team notes or spreadsheets
- battle data sources if the project expands beyond planning
