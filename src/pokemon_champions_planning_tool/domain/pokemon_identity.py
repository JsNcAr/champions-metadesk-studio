import re
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


# Species whose plain id names a specific default form. PokéAPI and Showdown both file
# these under the bare species id, so the name alone hides which form it is; the label is
# shown next to the name wherever a Pokémon is rendered. Maushold is left out on purpose:
# Showdown's default is Family of Three while PokéAPI's is Family of Four.
DEFAULT_FORM_LABELS: dict[str, str] = {
    "basculegion": "Male",
    "meowstic": "Male",
    "pyroar": "Male",
    "indeedee": "Male",
    "oinkologne": "Male",
    "aegislash": "Shield",
    "lycanroc": "Midday",
    "mimikyu": "Disguised",
    "morpeko": "Full Belly",
    "palafin": "Zero",
    "gourgeist": "Average",
    "urshifu": "Single Strike",
    "ogerpon": "Teal Mask",
    "tatsugiri": "Curly",
    "toxtricity": "Amped",
}


def default_form_label(canonical_id: str | None) -> str | None:
    """The implicit form behind a bare species id ("basculegion" → "Male"), else None."""
    return DEFAULT_FORM_LABELS.get((canonical_id or "").strip().lower())


def qualified_name(display_name: str, canonical_id: str | None) -> str:
    """``display_name`` with the implicit default form appended: "Basculegion (Male)"."""
    label = default_form_label(canonical_id)
    return f"{display_name} ({label})" if label and label.lower() not in display_name.lower() else display_name


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


# PokeAPI species whose own name contains a hyphen. Showdown strips those hyphens
# ("chien-pao" -> "chienpao"), so they must not be read as species + form. Everything
# else containing a hyphen is a form, and Showdown keeps that separator.
# Note the pairs this distinguishes: "nidoran-f" is a species, "indeedee-f" is a form.
_HYPHENATED_SPECIES: frozenset[str] = frozenset({
    "nidoran-f", "nidoran-m", "mr-mime", "mime-jr", "mr-rime", "ho-oh", "porygon-z",
    "type-null", "jangmo-o", "hakamo-o", "kommo-o",
    "tapu-koko", "tapu-lele", "tapu-bulu", "tapu-fini",
    "wo-chien", "chien-pao", "ting-lu", "chi-yu",
    "great-tusk", "scream-tail", "brute-bonnet", "flutter-mane", "slither-wing",
    "sandy-shocks", "iron-treads", "iron-bundle", "iron-hands", "iron-jugulis",
    "iron-moth", "iron-thorns", "iron-valiant", "roaring-moon", "walking-wake",
    "iron-leaves", "gouging-fire", "raging-bolt", "iron-boulder", "iron-crown",
})

# Forms whose Showdown slug is not derivable from the PokeAPI identifier.
_SPRITE_SLUG_OVERRIDES: dict[str, str] = {
    # PokeAPI calls the Combat Breed simply "tauros-paldea"; Showdown names it in full.
    "tauros-paldea": "tauros-paldeacombat",
    # Single Strike Urshifu shares the base Urshifu sprite.
    "urshifu-single-strike": "urshifu",
}

_FALLBACK_SPRITE_URL = (
    "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items/poke-ball.png"
)
_SHOWDOWN_SPRITE_BASE = "https://play.pokemonshowdown.com/sprites/gen5"


def get_showdown_sprite_slug(pokemon_name_or_id: str) -> str:
    """Converts a species/form identifier into a Showdown sprite slug.

    Showdown names sprite files ``<species><-form>``, where each part has every
    non-alphanumeric character removed but the separator between species and form is
    kept: ``lycanroc-dusk``, ``tauros-paldeaaqua``, ``charizard-megax``. PokeAPI uses
    hyphens for both purposes, so the split is taken at the first hyphen unless the
    whole identifier is a species that legitimately contains one.
    """
    cid = format_api_name(pokemon_name_or_id)
    if not cid:
        return ""

    if cid in _SPRITE_SLUG_OVERRIDES:
        return _SPRITE_SLUG_OVERRIDES[cid]

    if cid in _HYPHENATED_SPECIES or "-" not in cid:
        return cid.replace("-", "")

    species, form = cid.split("-", 1)
    return f"{species}-{form.replace('-', '')}"


def get_pokemon_sprite_url(pokemon_name_or_id: str) -> str:
    """Returns a robust high-reliability sprite URL for any species or form identifier."""
    if not pokemon_name_or_id:
        return _FALLBACK_SPRITE_URL

    slug = get_showdown_sprite_slug(pokemon_name_or_id)
    if not slug:
        return _FALLBACK_SPRITE_URL

    return f"{_SHOWDOWN_SPRITE_BASE}/{slug}.png"


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


_CHAMPIONS_REG_RE = re.compile(
    r"(?:\b(?:REG(?:ULATION)?|CHAMPIONS|VGC)[\s.-]*)M-?([A-Za-z])\b|\bM-([A-Za-z])\b|\bM([B-Db-d])\b",
    re.IGNORECASE,
)
_SV_REG_RE = re.compile(r"\bREG(?:ULATION)?[\s.]*(?:SET\s+)?([A-Ha-h])\b", re.IGNORECASE)

# Species newly introduced / legal in Champions Regulation M-C
REGULATION_MC_SPECIES: frozenset[str] = frozenset({
    "arboliva", "baxcalibur", "cinderace", "farfetchd", "gogoat",
    "golisopod", "grapploct", "indeedee", "inteleon", "mabosstiff",
    "mr-mime", "pawmot", "perrserker", "persian", "pincurchin",
    "rillaboom", "salamence", "sirfetchd", "squawkabilly", "swalot",
    "thievul", "toxtricity", "toxtricity-low-key", "wigglytuff",
})


def normalize_format_regulation(raw_format: str, tournament_name: str | None = None) -> str:
    """Normalises diverse raw format labels into standard UI regulation names.

    If tournament_name is provided, checks it first for explicit regulation mentions
    (e.g., 'Reg M-C', '[M-C]', 'REG MC', 'Champions-MC'), which take precedence over
    stale or defaulted platform format codes.
    """
    # 1. Check tournament name first for Champions M-X regulation
    if tournament_name:
        m = _CHAMPIONS_REG_RE.search(tournament_name)
        if m:
            letter = next(g for g in m.groups() if g).upper()
            return f"Regulation M-{letter}"

    # 2. Check raw_format for Champions M-X regulation
    if raw_format:
        m = _CHAMPIONS_REG_RE.search(raw_format)
        if m:
            letter = next(g for g in m.groups() if g).upper()
            return f"Regulation M-{letter}"

    # 3. Check tournament name for standard VGC Reg A-H
    if tournament_name:
        m = _SV_REG_RE.search(tournament_name)
        if m:
            return f"Regulation {m.group(1).upper()}"

    # 4. Check raw_format for standard VGC Reg A-H
    if raw_format:
        m = _SV_REG_RE.search(raw_format)
        if m:
            return f"Regulation {m.group(1).upper()}"
        fmt = raw_format.strip()
        fmt_upper = fmt.upper()
        for letter in ["H", "G", "F", "E", "D", "C", "B", "A"]:
            if (
                f"REGULATION {letter}" in fmt_upper
                or f"REGULATION SET {letter}" in fmt_upper
                or f"REG {letter}" in fmt_upper
                or f"REG{letter}" in fmt_upper
                or fmt_upper.endswith(f"REG{letter}")
            ):
                return f"Regulation {letter}"
        return fmt

    return "Champions Season 1"


_SINGLES_TOURNAMENT_RE = re.compile(
    r"\b(singles|single\s+battle|1v1|3v3|6v6|bss)\b"
    r"|\bsingle\b(?![-\s]*elim)",
    re.IGNORECASE,
)


def classify_battle_format(tournament_name: str | None, raw_format: str | None = None) -> str:
    """Classifies whether a tournament is 'singles' or 'doubles'.

    Official Play! Pokémon VGC and standard community events are Doubles.
    Only events explicitly indicating Singles/3v3/6v6/1v1/BSS are classified as 'singles'.
    """
    if tournament_name and _SINGLES_TOURNAMENT_RE.search(tournament_name):
        return "singles"
    if raw_format and _SINGLES_TOURNAMENT_RE.search(raw_format):
        return "singles"
    return "doubles"


_MEGA_SUFFIX_RE = re.compile(r"-mega(-[xy])?$")
_BATTLE_ONLY_SUFFIXES = ("-gmax", "-primal", "-eternamax")


def base_canonical_id(canonical_id: str | None) -> str:
    """Strip Mega and similar battle-only form suffixes: "charizard-mega-y" -> "charizard".

    Regional and other persistent forms ("rotom-wash", "urshifu-rapid-strike") are kept:
    they are different Pokémon to own, whereas a Mega is the base species plus a stone.
    """
    cid = (canonical_id or "").lower().strip()
    cid = _MEGA_SUFFIX_RE.sub("", cid)
    for suffix in _BATTLE_ONLY_SUFFIXES:
        if cid.endswith(suffix):
            cid = cid[: -len(suffix)]
    return cid
