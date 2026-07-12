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
