"""Project-wide settings and storage defaults."""

import os
from pathlib import Path

APP_NAME = "Champions MetaDesk Studio"
# Shown in Settings › About; the README and NOTICE.md carry the same text.
DISCLAIMER = (
    "Champions MetaDesk Studio is an unofficial fan-made tool. It is not affiliated with, "
    "endorsed or sponsored by Nintendo, Game Freak, Creatures Inc. or The Pokémon Company. "
    "Pokémon and Pokémon character names are trademarks of their respective owners."
)
DEFAULT_CSV_FILENAME = "pokemon_team_stats.csv"
# Where the SQLite file lives. Relative paths resolve against the working directory.
# Override with PCPT_DATABASE=/path/to/file.db; preferences.json sits beside it unless
# PCPT_PREFERENCES points elsewhere.
DEFAULT_DATABASE_FILENAME = os.environ.get("PCPT_DATABASE", "pokemon_champions.db")
DEFAULT_PREFERENCES_FILENAME = os.environ.get(
    "PCPT_PREFERENCES", str(Path(DEFAULT_DATABASE_FILENAME).parent / "preferences.json")
)
# Absolute on purpose. Flet resolves a *relative* assets_dir against the directory of
# sys.argv[0], not the working directory, so "assets" became
# src/pokemon_champions_planning_tool/assets — a path that does not exist, which makes
# Flet serve no assets at all. The sprite cache meanwhile wrote to ./assets/sprites, so
# nothing it downloaded was ever reachable. Resolving here keeps the two in step.
DEFAULT_ASSETS_DIR = str(Path(os.environ.get("PCPT_ASSETS_DIR", "assets")).resolve())
DEFAULT_SPRITE_CACHE_DIR = str(
    Path(os.environ.get("PCPT_SPRITE_CACHE_DIR", str(Path(DEFAULT_ASSETS_DIR) / "sprites"))).resolve()
)
POKEAPI_BASE_URL = "https://pokeapi.co/api/v2"
POKEAPI_TIMEOUT_SECONDS = 5

CSV_HEADERS = [
    "Pokémon",
    "Form",
    "Ability",
    "HP",
    "Attack",
    "Defense",
    "Sp. Atk",
    "Sp. Def",
    "Speed",
    "Total",
]

# Backward-compatible alias while the codebase is still mid-refactor.
HEADERS = CSV_HEADERS

# Tournament data sources
LIMITLESS_API_BASE_URL = "https://play.limitlesstcg.com/api"
LIMITLESS_PAGE_SIZE = 200
LIMITLESS_CHAMPIONS_FORMATS = {"M-A", "M-B", "M-C"}
LIMITLESS_MAX_AGE_DAYS = 365

VICTORY_ROAD_BASE_URL = "https://victoryroad.pro"
# Official events are discovered from Victory Road's season calendar pages
# (/{season}-season-calendar/). Each finished event page is read once; at most this many
# new pages per sync run, since each is a 1–2 MB WordPress render.
VICTORY_ROAD_PAGES_PER_RUN = 2
VICTORY_ROAD_CALENDAR_MAX_AGE_HOURS = 24
# An official event whose Victory Road page has no team list yet is retried on every
# sync while it ended this recently (results usually appear within days)...
VICTORY_ROAD_RESULTS_GRACE_DAYS = 14
# ...then at most once per this many days, so a slow update does not make the event
# vanish for good...
VICTORY_ROAD_SLOW_RETRY_DAYS = 3
# ...and it is given up on once it ended this long ago with still no team list.
VICTORY_ROAD_GIVE_UP_DAYS = 45
# Placements ingested per official event (Regionals publish hundreds of sheets).
VICTORY_ROAD_MAX_PLACEMENT = int(os.environ.get("PCPT_VR_MAX_PLACEMENT", "64") or 64)
VRPASTE_BACKEND_URL = "https://vrpaste-backend.vercel.app/api/paste"
POKEPAST_JSON_URL = "https://pokepast.es/{id}/json"

# Move catalogue: every move (Showdown data bundle) plus the Champions learnsets and
# move changes from the Showdown repository. Re-synced when older than this.
SHOWDOWN_MOVES_JSON_URL = "https://play.pokemonshowdown.com/data/moves.json"
SHOWDOWN_CHAMPIONS_LEARNSETS_URL = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions/learnsets.ts"
SHOWDOWN_CHAMPIONS_MOVES_URL = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions/moves.ts"
MOVE_CATALOG_MAX_AGE_DAYS = 30
# Bump when the stored move shape changes; a lower stored version triggers one re-sync.
MOVE_CATALOG_SCHEMA_VERSION = 2
# Species catalogue (base stats, abilities, weights, forms) for the damage calculator
SHOWDOWN_POKEDEX_JSON_URL = "https://play.pokemonshowdown.com/data/pokedex.json"
SHOWDOWN_CHAMPIONS_FORMATS_DATA_URL = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions/formats-data.ts"
SPECIES_CATALOG_SCHEMA_VERSION = 1

TOURNAMENT_SYNC_TIMEOUT = 12

# Limitless allows 50 requests per 5 minutes (``ratelimit`` response header). A sync
# never spends the last LIMITLESS_RATE_RESERVE of that window, so a second launch or a
# manual "Sync now" shortly afterwards still has room instead of hitting 429s.
LIMITLESS_RATE_RESERVE = 8
# Standings requests per sync run (the rate budget above may stop a run earlier).
LIMITLESS_STANDINGS_PER_RUN = 40
# A tournament with no published standings is retried while it is this recent — events
# are listed on the day they run and decklists appear when they finish.
RECENT_EVENT_GRACE_DAYS = 3
# The launch-time sync is skipped when a sync completed this recently and no backlog
# is waiting; "Sync now" in Settings always runs.
STARTUP_SYNC_MIN_INTERVAL_HOURS = 6
TOURNAMENT_USER_AGENT = "ChampionsMetaDeskStudio/1.0 (https://github.com)"

