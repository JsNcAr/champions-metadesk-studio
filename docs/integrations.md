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

- Species lookups go to `/pokemon/<species>`; on a 404 the adapter asks
  `/pokemon-species/<species>` for the default variety and fetches that form instead
  (basculegion → basculegion-male, aegislash → aegislash-shield, lycanroc → lycanroc-midday,
  mimikyu, morpeko, palafin, maushold, gourgeist, meowstic, pyroar). The stored record keeps
  the species slug as its id so it matches the Champions catalogue, rosters and learnsets,
  and `form_name` carries the default form's label ("Male", "Shield") so the UI can say which
  variation it is; tournament rosters get the same label from `DEFAULT_FORM_LABELS`.
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
- **Endpoints**: `/tournaments?game=VGC` (200 per page; `format=` is honoured server-side) and `/tournaments/{id}/standings` (full decklists).
- **Budget**: the API allows 50 requests per 5 minutes and reports it in a `ratelimit` header (`r=` remaining, `t=` seconds to reset). The provider reads it after every response and stops a standings batch when only a reserve (8) is left; the per-run cap is 40 standings requests.
- **Incremental listing**: paging stops at the first page made entirely of Champions-format tournaments already stored (one request in steady state). A forced sync re-reads the whole one-year window.
- **Retries** only for what can succeed on retry: 429 (waiting for `Retry-After` or the window reset, capped at 90 s), 5xx, connection errors and timeouts. Other 4xx raise at once.
- **Unfinished events**: no standings request before an event's date; an empty answer from an event less than three days old is retried later instead of being marked complete.
- **Backlog**: tournaments whose standings were not fetched yet stay `standings_synced=False` and are drained a slice per run, limited to the one-year window. The launch-time sync is skipped when one completed within six hours and nothing is pending; "Sync now" always runs, and only one sync runs per process.
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
- **Fetch once**: an event already ingested completely is never requested again; a partially ingested event (some pastes failed) stays pending and only its missing pastes are fetched on the next run. Paste fetches get one retry and a short pause.
- **Discovery**: the season calendar pages (`/{season}-season-calendar/`, this season and the next, re-read at most every 24 h or on a forced sync) list every event with its dates, name and city, winner and format. Each row becomes a pending tournament (date = last day, game and regulation from the Format cell, tier from the name). The static registry (`OFFICIAL_EVENT_SLUGS`) seeds the same way, so the app works before the first calendar read, and existing rows are never overwritten.
- **Reading queue**: per run, at most `VICTORY_ROAD_PAGES_PER_RUN` (2) finished, pending events are read, newest first; a page with no sheets yet is retried while the event ended within `VICTORY_ROAD_RESULTS_GRACE_DAYS` (14), then closed. Up to `VICTORY_ROAD_MAX_PLACEMENT` sheets (64, env `PCPT_VR_MAX_PLACEMENT`) are ingested per event. Events are classified into tiers (Worlds, International, Regional, Special Event) from the organizer and name; everything from Limitless is community.

> **Fragility note**: the cell layout was hand-verified against victoryroad.pro on 2026-08-31
> (see the module docstring in `victory_road_provider.py`). Any site redesign will silently
> yield zero standings rather than an error, so `fetch_event` logs and returns `None` when no
> paste entries are found.

---

## Showdown & Poképaste Integration

- **Text Export / Import**: Parses standard Pokémon Showdown importable text format into live team slot configurations (species, item, ability, stat points, moves). Showdown's Champions format carries stat points on the `EVs:` line; a mainline 252-style spread is converted with `points_from_evs` and flagged, and `IVs:`/`Level:` lines are ignored with a warning since both are fixed in Champions.
- **Direct Poképaste Publishing**: Posts team text to `https://pokepast.es/create` and returns shareable Poképaste URLs.
- **Showdown Sprite CDN**: High-reliability sprite URL generator (`get_pokemon_sprite_url`) fetching gen5 sprites from `play.pokemonshowdown.com/sprites/gen5/` with 100% form coverage for regional variants (Hisuian Arcanine, Hisuian Samurott), special forms (Floette Eternal, Calyrex forms, Ogerpon masks), and Mega evolutions.

---

## Move Catalogue (Pokémon Showdown)

Three static files, fetched at most every 30 days or from Settings:
- `https://play.pokemonshowdown.com/data/moves.json` — every move with type, category, base power, accuracy, PP, priority, target and description.
- `data/mods/champions/learnsets.ts` (Showdown repository) — the moves each species can learn in Champions. Mega forms use their base species' learnset.
- `data/mods/champions/moves.ts` — moves Champions removed (`isNonstandard: "Past"`) or rebalanced. Removed moves are never offered.

Stored in `moves` (with a `mechanics` JSON column: flags, secondaries, recoil, drain, multihit, stat overrides… for the damage formula), `learnsets` and `move_catalog_meta`. A `schema_version` on the meta row forces one re-sync when the stored shape changes; legality is "not removed by the mod and (current in the base data or restored by the mod)".

**Species catalogue** — `pokedex.json` from the same bundle plus `data/mods/champions/formats-data.ts` for Champions legality: base stats, types, abilities, weight, forms and required Mega Stones for every species (stored in `species_catalog`, ~1.4k rows, 314 legal), synced with the moves. `domain/species.py` maps our ids onto Showdown's (basculegion-male → basculegion, urshifu-single-strike → urshifu…). Species keys are Showdown's (`urshifurapidstrike`); `domain/moves.py` maps our PokéAPI-style ids to them with a fallback to the nearest keyed form. Per-species move usage comes from the `moves` column on `tournament_team_members`, aggregated with `json_each`.

---

## CSV Export

CSV remains a useful export format for spreadsheet tools.
- Written on demand from the Box toolbar's Export button (no longer on every write).
- Stable column order containing canonical identity, display name, base stats, types, and favorite status.

---

## Runtime Configuration & Environment

The storage location and sync behavior can be configured via environment variables:
- `PCPT_DATABASE`: Path of the SQLite database file (default: `pokemon_champions.db` in working directory).
- `PCPT_PREFERENCES`: Path of the view-preferences JSON file (default: `preferences.json` beside the database).
- `PCPT_VR_MAX_PLACEMENT`: Maximum placements ingested per official Victory Road event (default: `64`).

---

## Future Integration Backlog

Optional future integrations:
- Offline sprite disk caching (Flutter in-memory caching currently covers session duration).
- Direct battle log parser (Showdown `.log` file analyzer).
