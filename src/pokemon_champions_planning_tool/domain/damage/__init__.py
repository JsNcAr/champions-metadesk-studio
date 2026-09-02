"""Damage engine for Pokémon Champions.

A Python port of the Pokémon Champions mechanics module of the Smogon damage calculator
(https://github.com/smogon/damage-calc, MIT — see NOTICE.md), pinned to the commit in
``PORTED_CALC_COMMIT``. ``tests/fixtures/damage/`` holds ~1000 scenarios generated from that
build; ``tests/test_damage_fixtures.py`` replays them roll for roll.

Deliberately not ported (absent from Champions or from the module): Z-Moves, Dynamax, other
generations, Terastallization/Stellar/Terapagos, the Ruin abilities, Protosynthesis/Quark
Drive/Booster Energy, Nature Power, Flower Gift, Battery, Power Spot, Steely Spirit.
"""

from __future__ import annotations

from .abilities import ability_names, canonical_ability_name
from .items import canonical_item_name, champions_items
from .mechanics import calculate_raw
from .result import DamageResult
from .state import APP_TO_CALC_STAT, CALC_TO_APP_STAT, CalcMove, CalcPokemon, Field, Side

PORTED_CALC_COMMIT = "2c50a89d9e369289965b1448a6f5c1b7d41520c7"


def calculate(attacker: CalcPokemon, defender: CalcPokemon, move: CalcMove, field: Field | None = None) -> DamageResult:
    """Damage of ``move`` from ``attacker`` to ``defender`` under ``field`` (Singles by default)."""
    raw = calculate_raw(attacker, defender, move, field)
    return DamageResult(raw.attacker, raw.defender, raw.move, raw.field, raw.damage, raw.desc)


__all__ = [
    "APP_TO_CALC_STAT", "CALC_TO_APP_STAT", "PORTED_CALC_COMMIT", "CalcMove", "CalcPokemon", "DamageResult", "Field", "Side",
    "ability_names", "calculate", "canonical_ability_name", "canonical_item_name", "champions_items",
]
