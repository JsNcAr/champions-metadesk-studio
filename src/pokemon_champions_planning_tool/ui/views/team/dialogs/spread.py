"""Spread presets for the slot editor's stat-point editor (Champions: 0–32 per stat, 66 total).

The spread is edited inline in the expanded slot card; this module keeps the presets it offers.
"""

from __future__ import annotations

# Presets in stat points (a "252 / 252 / 4" EV spread is 32 / 32 / 2 — see points_from_evs).
PRESETS: dict[str, dict[str, int]] = {
    "Physical sweeper": {"attack": 32, "speed": 32, "hp": 2},
    "Special sweeper": {"special_attack": 32, "speed": 32, "hp": 2},
    "Bulky physical": {"hp": 32, "defense": 32, "special_defense": 2},
    "Bulky special": {"hp": 32, "special_defense": 32, "defense": 2},
    "Trick Room": {"hp": 32, "attack": 32, "special_defense": 2},
    "Balanced": {"hp": 32, "defense": 17, "special_defense": 17},
}

__all__ = ["PRESETS"]
