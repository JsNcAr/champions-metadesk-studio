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

- All outbound HTTP in the project goes through the `requests` library; providers wrap
  failures in their own domain exception type (`LimitlessNetworkError`,
  `VictoryRoadNetworkError`, `VRPasteNetworkError`, `PokepastNetworkError`) so services
  never handle transport-level errors directly.
- Network failures must be handled gracefully.
- API naming rules must be normalized consistently.
- Repeated calls should eventually be cached.
- The app should tolerate partial data when some endpoints are unavailable.

## Limitless VGC API

The Limitless API (`play.limitlesstcg.com/api`) supplies official competitive tournament lists and player standings for Pokémon VGC events.

### Features & Rate-Limiting Strategy
- **Endpoints**: `/tournaments?game=VGC` and `/tournaments/{id}/standings`.
- **HTTP 429 Exponential Backoff**: Retries failed requests up to 3 times with progressive delays (`1s`, `2s`, `4s`).
- **Inter-Page Throttling**: Adds a 0.5s pause between paginated requests to prevent hitting server rate limits.
- **Defensive Parsing**: Safe integer conversion (`_safe_int`) handles missing or `None` values for placement standings gracefully.

---

## Victory Road Provider

Victory Road (`victoryroad.pro`) publishes official Premier Event team sheets and tournament results (e.g. LAIC 2026).

### Features & Web Scraping Strategy
- **HTML Parsing**: Parses WordPress / Elementor tournament result pages with pre-compiled
  `re` patterns from the standard library — no HTML parsing dependency is used. The strategy
  is *link-anchored*: it locates every Poképaste/VRPaste URL in the document, then walks
  backwards through the preceding ~3000 characters of `<td>` cells to recover the placement
  (first purely numeric cell) and the player handle (cell containing a bracketed `( handle )`).
- **Custom User-Agent & Timeouts**: Configured with a 25-second timeout, two retries, and
  modern browser headers to reliably fetch large event pages.
- **Poképaste Sheet Extraction**: Extracts Poképaste URLs and player standings directly into `TournamentTeamRecord`.

> **Fragility note**: the cell layout was hand-verified against victoryroad.pro on 2026-08-31
> (see the module docstring in `victory_road_provider.py`). Any site redesign will silently
> yield zero standings rather than an error, so `fetch_event` logs and returns `None` when no
> paste entries are found.

---

## Showdown & Poképaste Integration

- **Text Export / Import**: Parses standard Pokémon Showdown importable text format into live team slot configurations (species, item, ability, EV/IV spreads, moves).
- **Direct Poképaste Publishing**: Posts team text to `https://pokepast.es/create` and returns shareable Poképaste URLs.
- **Showdown Sprite CDN**: High-reliability sprite URL generator (`get_pokemon_sprite_url`) fetching gen5 sprites from `play.pokemonshowdown.com/sprites/gen5/` with 100% form coverage for regional variants (Hisuian Arcanine, Hisuian Samurott), special forms (Floette Eternal, Calyrex forms, Ogerpon masks), and Mega evolutions.

---

## CSV Export

CSV remains a useful export format for spreadsheet tools.
- Automatically synchronized with `BoxEntryRecord` mutations.
- Stable column order containing canonical identity, display name, base stats, types, and favorite status.

---

## Future Integration Backlog

Optional future integrations:
- Offline sprite disk caching.
- Custom SQLite database file configuration via environment variables or UI setting.
- Direct battle log parser (Showdown `.log` file analyzer).
