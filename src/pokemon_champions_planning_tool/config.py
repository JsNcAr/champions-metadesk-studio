"""Project-wide settings and storage defaults."""

APP_NAME = "Pokemon Champions Planning Tool"
DEFAULT_CSV_FILENAME = "pokemon_team_stats.csv"
DEFAULT_DATABASE_FILENAME = "pokemon_champions.db"
DEFAULT_PREFERENCES_FILENAME = "preferences.json"
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
VRPASTE_BACKEND_URL = "https://vrpaste-backend.vercel.app/api/paste"
POKEPAST_JSON_URL = "https://pokepast.es/{id}/json"

# Move catalogue: every move (Showdown data bundle) plus the Champions learnsets and
# move changes from the Showdown repository. Re-synced when older than this.
SHOWDOWN_MOVES_JSON_URL = "https://play.pokemonshowdown.com/data/moves.json"
SHOWDOWN_CHAMPIONS_LEARNSETS_URL = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions/learnsets.ts"
SHOWDOWN_CHAMPIONS_MOVES_URL = "https://raw.githubusercontent.com/smogon/pokemon-showdown/master/data/mods/champions/moves.ts"
MOVE_CATALOG_MAX_AGE_DAYS = 30

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
TOURNAMENT_USER_AGENT = "PokemonChampionsPlanningTool/1.0 (https://github.com)"

