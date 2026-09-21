"""On/off chips for the calculator (side conditions, statuses): readable in both states."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...theme import Palette


def toggle_chip(label: str, on_select: Callable[[], None], *, tooltip: str | None = None, selected: bool = False) -> ft.Chip:
    chip = ft.Chip(label=ft.Text(label), selected=selected, show_checkmark=False, tooltip=tooltip,
                   visual_density=ft.VisualDensity.COMPACT, on_select=lambda _e: on_select())
    set_toggle(chip, selected)
    return chip


def set_toggle(chip: ft.Chip, selected: bool, label: str | None = None) -> None:
    """Selected chips read brighter as well as filled, so the state never rests on colour alone."""
    text = label if label is not None else getattr(chip.label, "value", "")
    chip.selected = selected
    chip.label = ft.Text(text, color=Palette.ON_SURFACE if selected else Palette.ON_SURFACE_VARIANT,
                         weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500)
