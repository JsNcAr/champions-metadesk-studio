"""Project-wide settings and storage defaults."""

APP_NAME = "Pokemon Champions Planning Tool"
DEFAULT_CSV_FILENAME = "pokemon_team_stats.csv"
DEFAULT_DATABASE_FILENAME = "pokemon_champions.db"
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

TOURNAMENT_SYNC_TIMEOUT = 12
TOURNAMENT_USER_AGENT = "PokemonChampionsPlanningTool/1.0 (https://github.com)"

