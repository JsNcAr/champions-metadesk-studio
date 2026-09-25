"""How a matchup class looks and reads: the opponents list and the team rail share these.

Classes are from "your" side (see ``state.classify``): in the opponents list "you" are the
attacker and each card is a rival; in the team rail each card is one of your Pokémon and the
rival is the defender.
"""

from __future__ import annotations

import flet as ft

from ...theme import Palette, alpha

CLASS_TONES = {"threat": "error", "wall": "warning", "neutral": "neutral", "mitigated": "info", "crushed": "success"}
CLASS_HELP = {
    "threat": "KOs you in one hit before you can, or in two while you need three or more",
    "wall": "you need four hits or more",
    "neutral": "an even race",
    "mitigated": "you win the race",
    "crushed": "you KO in one hit and they cannot KO you first",
}
CLASS_BG = {
    "threat": alpha(Palette.ERROR, 0.18),
    "wall": alpha(Palette.WARNING, 0.18),
    "neutral": Palette.SURFACE_2,
    "mitigated": alpha(Palette.SECONDARY, 0.15),
    "crushed": alpha(Palette.SUCCESS, 0.18),
}
# The class's own colour, for small marks (the opponents filter's dots).
CLASS_COLOR = {"threat": Palette.ERROR, "wall": Palette.WARNING, "neutral": Palette.OUTLINE, "mitigated": Palette.SECONDARY, "crushed": Palette.SUCCESS}
CLASS_BORDER = {
    "threat": ft.Border.all(1, alpha(Palette.ERROR, 0.40)),
    "wall": ft.Border.all(1, alpha(Palette.WARNING, 0.40)),
    "neutral": ft.Border.all(1, Palette.OUTLINE_VARIANT),
    "mitigated": ft.Border.all(1, alpha(Palette.SECONDARY, 0.35)),
    "crushed": ft.Border.all(1, alpha(Palette.SUCCESS, 0.40)),
}

__all__ = ["CLASS_BG", "CLASS_BORDER", "CLASS_COLOR", "CLASS_HELP", "CLASS_TONES"]
