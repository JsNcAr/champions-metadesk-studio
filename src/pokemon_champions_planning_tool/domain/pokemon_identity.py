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


# Explicit canonical overrides for common VGC / Showdown display names
_SPECIES_ALIAS_MAP: dict[str, str] = {
    "rapid strike urshifu": "urshifu-rapid-strike",
    "urshifu rapid strike": "urshifu-rapid-strike",
    "urshifu-rapid-strike": "urshifu-rapid-strike",
    "single strike urshifu": "urshifu-single-strike",
    "urshifu single strike": "urshifu-single-strike",
    "urshifu-single-strike": "urshifu-single-strike",
    "hearthflame mask ogerpon": "ogerpon-hearthflame",
    "ogerpon hearthflame": "ogerpon-hearthflame",
    "ogerpon-hearthflame": "ogerpon-hearthflame",
    "cornerstone mask ogerpon": "ogerpon-cornerstone",
    "ogerpon cornerstone": "ogerpon-cornerstone",
    "ogerpon-cornerstone": "ogerpon-cornerstone",
    "wellspring mask ogerpon": "ogerpon-wellspring",
    "ogerpon wellspring": "ogerpon-wellspring",
    "ogerpon-wellspring": "ogerpon-wellspring",
    "bloodmoon ursaluna": "ursaluna-bloodmoon",
    "ursaluna bloodmoon": "ursaluna-bloodmoon",
    "ursaluna-bloodmoon": "ursaluna-bloodmoon",
    "eternal flower floette": "floette-eternal",
    "floette eternal": "floette-eternal",
    "floette-eternal": "floette-eternal",
    "shadow rider calyrex": "calyrex-shadow",
    "calyrex shadow": "calyrex-shadow",
    "ice rider calyrex": "calyrex-ice",
    "calyrex ice": "calyrex-ice",
    "landorus therian": "landorus-therian",
    "thundurus therian": "thundurus-therian",
    "tornadus therian": "tornadus-therian",
    "enamorus therian": "enamorus-therian",
}


def format_api_name(pokemon_name: str) -> str:
    """
    Translates human-readable names into PokéAPI's internal URL format.
    Example: "Mega Raichu X" -> "raichu-mega-x"
    """
    cleaned = pokemon_name.strip().lower()
    if not cleaned:
        return ""

    if cleaned in _SPECIES_ALIAS_MAP:
        return _SPECIES_ALIAS_MAP[cleaned]

    words = cleaned.split()

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


def normalize_format_regulation(raw_format: str) -> str:
    """Normalises diverse raw format labels into standard UI regulation names."""
    if not raw_format:
        return "Champions Season 1"

    fmt = raw_format.strip()
    fmt_upper = fmt.upper()

    if "M-B" in fmt_upper:
        return "Regulation M-B"
    if "M-A" in fmt_upper:
        return "Regulation M-A"
    if "M-C" in fmt_upper:
        return "Regulation M-C"

    # Match "Regulation Set H", "Regulation H", "Reg H", "REGH", etc.
    for letter in ["H", "G", "F", "E", "D", "C", "B", "A"]:
        if f"REGULATION {letter}" in fmt_upper or f"REGULATION SET {letter}" in fmt_upper or f"REG {letter}" in fmt_upper or f"REG{letter}" in fmt_upper or fmt_upper.endswith(f"REG{letter}"):
            return f"Regulation {letter}"

    return fmt


