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
    "floette eternal flower": "floette-eternal",
    "hisuian arcanine": "arcanine-hisui",
    "arcanine hisuian": "arcanine-hisui",
    "arcanine hisui": "arcanine-hisui",
    "arcanine-hisui": "arcanine-hisui",
    "hisuian-arcanine": "arcanine-hisui",
    "hisuian samurott": "samurott-hisui",
    "samurott-hisui": "samurott-hisui",
    "hisuian zoroark": "zoroark-hisui",
    "zoroark-hisui": "zoroark-hisui",
    "hisuian goodra": "goodra-hisui",
    "goodra-hisui": "goodra-hisui",
    "hisuian decidueye": "decidueye-hisui",
    "decidueye-hisui": "decidueye-hisui",
    "hisuian typhlosion": "typhlosion-hisui",
    "typhlosion-hisui": "typhlosion-hisui",
    "shadow rider calyrex": "calyrex-shadow",
    "calyrex shadow": "calyrex-shadow",
    "ice rider calyrex": "calyrex-ice",
    "calyrex ice": "calyrex-ice",
    "landorus therian": "landorus-therian",
    "thundurus therian": "thundurus-therian",
    "tornadus therian": "tornadus-therian",
    "enamorus therian": "enamorus-therian",
}


def get_pokemon_sprite_url(pokemon_name_or_id: str) -> str:
    """Returns a robust high-reliability sprite URL for any species or form identifier."""
    if not pokemon_name_or_id:
        return "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png"

    cid = format_api_name(pokemon_name_or_id)

    # Custom Showdown sprite overrides
    custom_map = {
        "urshifu-rapid-strike": "https://play.pokemonshowdown.com/sprites/gen5/urshifu-rapidstrike.png",
        "urshifu-single-strike": "https://play.pokemonshowdown.com/sprites/gen5/urshifu.png",
    }
    if cid in custom_map:
        return custom_map[cid]

    if "-mega-x" in cid:
        showdown_slug = cid.replace("-mega-x", "-megax")
        parts = showdown_slug.rsplit("-", 1)
        showdown_slug = parts[0].replace("-", "") + "-" + parts[1]
        return f"https://play.pokemonshowdown.com/sprites/gen5/{showdown_slug}.png"

    if "-mega-y" in cid:
        showdown_slug = cid.replace("-mega-y", "-megay")
        parts = showdown_slug.rsplit("-", 1)
        showdown_slug = parts[0].replace("-", "") + "-" + parts[1]
        return f"https://play.pokemonshowdown.com/sprites/gen5/{showdown_slug}.png"

    if "-mega" in cid:
        showdown_slug = cid.replace("-mega", "mega")
        parts = showdown_slug.rsplit("mega", 1)
        showdown_slug = parts[0].replace("-", "") + "-mega"
        return f"https://play.pokemonshowdown.com/sprites/gen5/{showdown_slug}.png"

    form_suffixes = [
        "-hisui", "-alola", "-galar", "-paldea", "-eternal",
        "-shadow", "-ice", "-therian", "-hearthflame", "-wellspring",
        "-cornerstone", "-bloodmoon", "-primal"
    ]
    matched_suffix = None
    for suf in form_suffixes:
        if cid.endswith(suf):
            matched_suffix = suf
            break

    if matched_suffix:
        base = cid[:-len(matched_suffix)].replace("-", "")
        showdown_slug = f"{base}{matched_suffix}"
    else:
        showdown_slug = cid.replace("-", "")

    return f"https://play.pokemonshowdown.com/sprites/gen5/{showdown_slug}.png"


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


