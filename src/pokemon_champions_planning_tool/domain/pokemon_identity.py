"""Canonical Pokemon naming helpers."""


def format_display_name(api_name):
    """Converts a PokéAPI identifier into a consistent display name."""
    if not api_name:
        return ""

    if api_name.endswith("-mega-x"):
        return f"Mega {api_name.removesuffix('-mega-x').title()} X"
    if api_name.endswith("-mega-y"):
        return f"Mega {api_name.removesuffix('-mega-y').title()} Y"
    if api_name.endswith("-mega"):
        return f"Mega {api_name.removesuffix('-mega').title()}"

    regional_labels = {
        "alola": "Alolan",
        "galar": "Galarian",
        "hisui": "Hisuian",
        "paldea": "Paldean",
    }
    for region, label in regional_labels.items():
        suffix = f"-{region}"
        if api_name.endswith(suffix):
            return f"{label} {api_name.removesuffix(suffix).title()}"

    return api_name.title()


def format_api_name(pokemon_name):
    """
    Translates human-readable names into PokéAPI's internal URL format.
    Example: "Mega Raichu X" -> "raichu-mega-x"
    """
    words = pokemon_name.strip().lower().split()

    if not words:
        return ""

    if words[0] == "mega":
        if len(words) == 3 and words[2] in ["x", "y"]:
            return f"{words[1]}-mega-{words[2]}"
        if len(words) == 2:
            return f"{words[1]}-mega"

    regional_map = {
        "alolan": "alola",
        "galarian": "galar",
        "hisuian": "hisui",
        "paldean": "paldea",
    }
    if words[0] in regional_map:
        return f"{words[1]}-{regional_map[words[0]]}"

    return "-".join(words)
