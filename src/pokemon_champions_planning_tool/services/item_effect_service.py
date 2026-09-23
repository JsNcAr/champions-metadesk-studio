"""Pure functional domain service for computing item stat effects and validating item guardrails.

This service contains ZERO I/O, database queries, or external network calls.
It operates purely on in-memory domain models (Item, ItemRecord, PokemonStats).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math

from ..domain.entities.item import Item
from ..domain.entities.pokemon_stats import PokemonStats
from ..infrastructure.database.models import ItemRecord


@dataclass
class ValidationResult:
    """Structured result of an item assignment guardrail validation."""

    is_valid: bool = True
    warning: str | None = None
    error: str | None = None
    unlocked_form: str | None = None
    stat_modifiers: dict[str, float] = field(default_factory=dict)


def compute_effective_stats(
    base_stats: PokemonStats,
    item: ItemRecord | Item | None,
) -> PokemonStats:
    """Computes modified PokemonStats with item stat multipliers applied.

    Floor/truncation is applied to resulting integer stat values per standard
    competitive Pokémon calculation rules. Pure function.
    """
    if not item:
        return base_stats

    # Extract stat modifiers dict whether passed an Item domain model or ItemRecord
    modifiers = item.stat_modifiers if hasattr(item, "stat_modifiers") else {}
    if not modifiers:
        return base_stats

    def _apply(val: int, multiplier: float) -> int:
        return math.floor(val * multiplier)

    return PokemonStats(
        hp=base_stats.hp,  # Items like Choice Scarf never modify HP
        attack=_apply(base_stats.attack, modifiers.get("attack", 1.0)),
        defense=_apply(base_stats.defense, modifiers.get("defense", 1.0)),
        special_attack=_apply(base_stats.special_attack, modifiers.get("special_attack", 1.0)),
        special_defense=_apply(base_stats.special_defense, modifiers.get("special_defense", 1.0)),
        speed=_apply(base_stats.speed, modifiers.get("speed", 1.0)),
    )


def validate_item_assignment(
    item: ItemRecord | Item | None,
    species_name: str | None,
    team_items: list[ItemRecord | Item | None] | None = None,
    *,
    mega: bool = True,
    one_mega_per_team: bool = True,
) -> ValidationResult:
    """Validates whether an item can be held by a given species and team slot.

    Guardrail rules:
      1. Legality: Items illegal in Champions yield a yellow/amber warning.
      2. Mega Stone species mismatch: Charizardite X held by Pikachu yields a red error.
      3. Mega Stone species match: Unlocks the target form (e.g. 'mega-x').
      4. Multi-Mega team limit: Second Mega Stone on team yields a warning.

    ``mega`` and ``one_mega_per_team`` come from the team's format: without Mega Evolution
    a stone unlocks nothing (and says so); without the limit, rule 4 is skipped.

    Pure function — zero I/O or DB access.
    """
    if not item:
        return ValidationResult(is_valid=True)

    is_legal = getattr(item, "is_champions_legal", True)
    display_name = getattr(item, "display_name", "Selected Item")
    target_species = getattr(item, "target_species", None)
    target_form = getattr(item, "target_form", None)
    stat_modifiers = getattr(item, "stat_modifiers", {}) or {}

    warning: str | None = None
    error: str | None = None
    unlocked_form: str | None = None

    # Rule 1: Champions format legality check
    if not is_legal:
        warning = f"{display_name} is not available in Pokémon Champions format."

    # Rule 2 & 3: Mega Stone species matching check
    if target_species and not mega:
        warning = warning or "Mega Evolution is not part of this team's format."
    elif target_species:
        normalized_species = (species_name or "").strip().lower()
        if normalized_species and target_species.lower() != normalized_species:
            # Mismatch: Red error blocks form unlock
            error = f"{display_name} can only be held by {target_species.title()}."
            unlocked_form = None
        else:
            # Match: Unlock target form!
            unlocked_form = target_form

        # Rule 4: Multi-Mega Stone check across team
        if team_items and one_mega_per_team:
            other_megas = [
                i for i in team_items
                if i and i != item and getattr(i, "target_species", None) is not None
            ]
            if other_megas:
                warning = (
                    warning or "Only one Pokémon per team can Mega Evolve in battle."
                )

    is_valid = error is None

    return ValidationResult(
        is_valid=is_valid,
        warning=warning,
        error=error,
        unlocked_form=unlocked_form,
        stat_modifiers=dict(stat_modifiers),
    )
