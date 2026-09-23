"""Type effectiveness chart (Generation VI onward: Fairy included, Steel no longer
resists Ghost/Dark) and the defensive summaries built on it.

Everything here is pure: no I/O, no Flet. Type names are the lowercase PokéAPI names
used throughout the domain (``"fire"``, ``"fighting"`` …).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

TYPES: tuple[str, ...] = (
    "normal", "fire", "water", "electric", "grass", "ice", "fighting", "poison", "ground",
    "flying", "psychic", "bug", "rock", "ghost", "dragon", "dark", "steel", "fairy",
)

# Non-neutral matchups only: ATTACK[attacking][defending] -> multiplier.
# Anything absent is 1.0.
_ATTACK: dict[str, dict[str, float]] = {
    "normal":   {"rock": 0.5, "ghost": 0.0, "steel": 0.5},
    "fire":     {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 2.0, "bug": 2.0, "rock": 0.5, "dragon": 0.5, "steel": 2.0},
    "water":    {"fire": 2.0, "water": 0.5, "grass": 0.5, "ground": 2.0, "rock": 2.0, "dragon": 0.5},
    "electric": {"water": 2.0, "electric": 0.5, "grass": 0.5, "ground": 0.0, "flying": 2.0, "dragon": 0.5},
    "grass":    {"fire": 0.5, "water": 2.0, "grass": 0.5, "poison": 0.5, "ground": 2.0, "flying": 0.5, "bug": 0.5, "rock": 2.0, "dragon": 0.5, "steel": 0.5},
    "ice":      {"fire": 0.5, "water": 0.5, "grass": 2.0, "ice": 0.5, "ground": 2.0, "flying": 2.0, "dragon": 2.0, "steel": 0.5},
    "fighting": {"normal": 2.0, "ice": 2.0, "poison": 0.5, "flying": 0.5, "psychic": 0.5, "bug": 0.5, "rock": 2.0, "ghost": 0.0, "dark": 2.0, "steel": 2.0, "fairy": 0.5},
    "poison":   {"grass": 2.0, "poison": 0.5, "ground": 0.5, "rock": 0.5, "ghost": 0.5, "steel": 0.0, "fairy": 2.0},
    "ground":   {"fire": 2.0, "electric": 2.0, "grass": 0.5, "poison": 2.0, "flying": 0.0, "bug": 0.5, "rock": 2.0, "steel": 2.0},
    "flying":   {"electric": 0.5, "grass": 2.0, "fighting": 2.0, "bug": 2.0, "rock": 0.5, "steel": 0.5},
    "psychic":  {"fighting": 2.0, "poison": 2.0, "psychic": 0.5, "dark": 0.0, "steel": 0.5},
    "bug":      {"fire": 0.5, "grass": 2.0, "fighting": 0.5, "poison": 0.5, "flying": 0.5, "psychic": 2.0, "ghost": 0.5, "dark": 2.0, "steel": 0.5, "fairy": 0.5},
    "rock":     {"fire": 2.0, "ice": 2.0, "fighting": 0.5, "ground": 0.5, "flying": 2.0, "bug": 2.0, "steel": 0.5},
    "ghost":    {"normal": 0.0, "psychic": 2.0, "ghost": 2.0, "dark": 0.5},
    "dragon":   {"dragon": 2.0, "steel": 0.5, "fairy": 0.0},
    "dark":     {"fighting": 0.5, "psychic": 2.0, "ghost": 2.0, "dark": 0.5, "fairy": 0.5},
    "steel":    {"fire": 0.5, "water": 0.5, "electric": 0.5, "ice": 2.0, "rock": 2.0, "steel": 0.5, "fairy": 2.0},
    "fairy":    {"fire": 0.5, "fighting": 2.0, "poison": 0.5, "dragon": 2.0, "dark": 2.0, "steel": 0.5},
}

# Display order for multiplier buckets, strongest weakness first.
BUCKETS: tuple[float, ...] = (4.0, 2.0, 1.0, 0.5, 0.25, 0.0)


def normalize_type(name: str) -> str:
    return (name or "").strip().lower()


def effectiveness(attacking: str, defending: str) -> float:
    """Single-type matchup multiplier. Unknown types are neutral."""
    return _ATTACK.get(normalize_type(attacking), {}).get(normalize_type(defending), 1.0)


def defensive_multiplier(attacking: str, defending_types: Sequence[str]) -> float:
    """Multiplier an attack of ``attacking`` type deals to a Pokémon of ``defending_types``
    (one or two types; duplicates and unknowns are ignored)."""
    result = 1.0
    seen: set[str] = set()
    for t in defending_types:
        key = normalize_type(t)
        if not key or key in seen or key not in _ATTACK:
            continue
        seen.add(key)
        result *= effectiveness(attacking, key)
    return result


def defensive_profile(defending_types: Sequence[str]) -> dict[str, float]:
    """Every attacking type -> multiplier against this typing."""
    return {atk: defensive_multiplier(atk, defending_types) for atk in TYPES}


# Abilities that change what hits a Pokémon, on top of its types (Showdown's rules; only
# the unconditional effects — Wonder Guard, Filter and the like are left to the calculator).
# Keys are lowercase with spaces for hyphens (``_ability_key``).
ABILITY_DEFENSE: dict[str, dict[str, float]] = {
    "levitate": {"ground": 0.0},
    "earth eater": {"ground": 0.0},
    "flash fire": {"fire": 0.0},
    "well baked body": {"fire": 0.0},
    "water absorb": {"water": 0.0},
    "storm drain": {"water": 0.0},
    "dry skin": {"water": 0.0},
    "volt absorb": {"electric": 0.0},
    "lightning rod": {"electric": 0.0},
    "motor drive": {"electric": 0.0},
    "sap sipper": {"grass": 0.0},
    "thick fat": {"fire": 0.5, "ice": 0.5},
    "heatproof": {"fire": 0.5},
    "water bubble": {"fire": 0.5},
    "purifying salt": {"ghost": 0.5},
    "fluffy": {"fire": 2.0},
}


def _ability_key(ability: str | None) -> str:
    return (ability or "").replace("-", " ").strip().lower()


def defensive_profile_with_ability(defending_types: Sequence[str], ability: str | None) -> tuple[dict[str, float], list[str]]:
    """``defensive_profile`` with the ability's changes, and one note per change
    ("Levitate: immune to Ground")."""
    profile = defensive_profile(defending_types)
    changes = ABILITY_DEFENSE.get(_ability_key(ability), {})
    notes: list[str] = []
    raw = (ability or "").strip()
    name = raw if any(c.isupper() for c in raw) else raw.replace("-", " ").title()
    for atk, factor in changes.items():
        before = profile.get(atk, 1.0)
        profile[atk] = before * factor
        if factor == 0.0:
            notes.append(f"{name}: immune to {atk.capitalize()}")
        elif factor < 1.0:
            notes.append(f"{name}: {atk.capitalize()} damage halved")
        else:
            notes.append(f"{name}: takes double {atk.capitalize()} damage")
    return profile, notes


def team_weakness_from_profiles(profiles: Iterable[dict[str, float] | None]) -> dict[str, tuple[int, int, int]]:
    """``team_weakness_summary`` from per-member profiles (so abilities count)."""
    members = [p for p in profiles if p]
    out: dict[str, tuple[int, int, int]] = {}
    for atk in TYPES:
        mults = [p.get(atk, 1.0) for p in members]
        out[atk] = (sum(1 for m in mults if m > 1.0), sum(1 for m in mults if 0.0 < m < 1.0), sum(1 for m in mults if m == 0.0))
    return out


def team_matrix_from_profiles(profiles: Iterable[dict[str, float] | None]) -> dict[str, list[float]]:
    """``team_defensive_matrix`` from per-member profiles; empty members read neutral."""
    members = list(profiles)
    return {atk: [(p.get(atk, 1.0) if p else 1.0) for p in members] for atk in TYPES}


def bucket_profile(profile: dict[str, float]) -> dict[float, list[str]]:
    """Group a profile by multiplier: {4.0: [...], 2.0: [...], 1.0: [...], 0.5: [...], 0.25: [...], 0.0: [...]}.
    Keys are always present (possibly empty), in BUCKETS order; type order follows TYPES."""
    buckets: dict[float, list[str]] = {b: [] for b in BUCKETS}
    for atk in TYPES:
        mult = profile.get(atk, 1.0)
        buckets.setdefault(mult, []).append(atk)
    return buckets


def team_weakness_summary(team_types: Iterable[Sequence[str]]) -> dict[str, tuple[int, int, int]]:
    """Per attacking type: (weak, resist, immune) counts across the given members.

    ``team_types`` is one type list per member; empty members are skipped.
    """
    members = [t for t in team_types if t]
    summary: dict[str, tuple[int, int, int]] = {}
    for atk in TYPES:
        weak = resist = immune = 0
        for types in members:
            mult = defensive_multiplier(atk, types)
            if mult == 0.0:
                immune += 1
            elif mult > 1.0:
                weak += 1
            elif mult < 1.0:
                resist += 1
        summary[atk] = (weak, resist, immune)
    return summary


def team_defensive_matrix(team_types: Iterable[Sequence[str]]) -> dict[str, list[float]]:
    """Per attacking type: the multiplier against each member, in member order."""
    members = list(team_types)
    return {atk: [defensive_multiplier(atk, types) if types else 1.0 for types in members] for atk in TYPES}


# -- offensive coverage -----------------------------------------------------------------------

def best_offensive_multiplier(move_types: Sequence[str], defending: str) -> float | None:
    """Best multiplier any of ``move_types`` (a slot's damaging moves) gets against a
    single-type defender; None when the slot has no damaging move."""
    types = [normalize_type(t) for t in move_types if normalize_type(t) in _ATTACK]
    if not types:
        return None
    return max(effectiveness(t, defending) for t in types)


def team_offensive_matrix(slot_move_types: Iterable[Sequence[str]]) -> dict[str, list[float | None]]:
    """Per defending type: the best multiplier each slot reaches with its damaging moves."""
    slots = list(slot_move_types)
    return {d: [best_offensive_multiplier(types, d) for types in slots] for d in TYPES}


def team_offensive_summary(matrix: dict[str, list[float | None]]) -> dict[str, tuple[int, int, int]]:
    """Per defending type: (slots hitting it super-effectively, neutrally, resisted or immune)."""
    out: dict[str, tuple[int, int, int]] = {}
    for d in TYPES:
        super_ = neutral = poor = 0
        for m in matrix.get(d, []):
            if m is None:
                continue
            if m > 1.0:
                super_ += 1
            elif m == 1.0:
                neutral += 1
            else:
                poor += 1
        out[d] = (super_, neutral, poor)
    return out


def uncovered_types(matrix: dict[str, list[float | None]]) -> list[str]:
    """Defending types no slot hits super-effectively (only meaningful once moves exist)."""
    return [d for d in TYPES if not any(m is not None and m > 1.0 for m in matrix.get(d, []))]
