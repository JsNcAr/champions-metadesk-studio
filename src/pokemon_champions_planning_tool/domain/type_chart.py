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
