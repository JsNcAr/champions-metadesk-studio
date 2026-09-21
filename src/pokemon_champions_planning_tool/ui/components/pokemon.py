"""Pokémon-specific components: type chips, stat bars, BST pill, identity row."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import flet as ft

from ...domain.entities.pokemon_stats import PokemonStats
from ..theme import (
    STAT_COLORS,
    STAT_LABELS,
    STAT_MAX,
    STAT_ORDER,
    STAT_TRACK,
    Palette,
    Radius,
    Space,
    alpha,
    on_type_color,
    type_color,
)
from .sprite import Sprite

ChipSize = Literal["sm", "md"]


class TypeChip(ft.Container):
    """Coloured, uppercase type label. Non-interactive; the colour is the icon."""

    def __init__(self, type_name: str, *, size: ChipSize = "md") -> None:
        super().__init__()
        self._label = ft.Text("", weight=ft.FontWeight.W_600)
        self.content = self._label
        self.border_radius = Radius.SM
        self._size = size
        self.set_type(type_name)

    def set_type(self, type_name: str) -> None:
        self._label.value = (type_name or "???").upper()
        self._label.size = 10 if self._size == "sm" else 11
        self._label.color = on_type_color(type_name)
        self.bgcolor = type_color(type_name)
        self.padding = (
            ft.Padding.symmetric(horizontal=6, vertical=1) if self._size == "sm"
            else ft.Padding.symmetric(horizontal=Space.SM, vertical=2)
        )


def type_chips(types: Sequence[str], *, size: ChipSize = "md") -> ft.Row:
    return ft.Row(spacing=Space.XS, tight=True, controls=[TypeChip(t, size=size) for t in types])


class BstPill(ft.Container):
    """`BST 534` — neutral, never accent-coloured (amber means selection)."""

    def __init__(self, total: int = 0) -> None:
        super().__init__()
        self._label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE)
        self.content = self._label
        self.bgcolor = Palette.SURFACE_3
        self.border_radius = Radius.PILL
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=2)
        self.set_total(total)

    def set_total(self, total: int, delta: int | None = None) -> None:
        text = f"BST {total}"
        if delta:
            text += f" ({delta:+d})"
        self._label.value = text


class StatBar(ft.Row):
    """`label 32 · bar · value 36`, normalised to /255 everywhere."""

    def __init__(self, stat: str, value: int = 0, *, delta_value: int | None = None) -> None:
        super().__init__(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.stat = stat
        colour = STAT_COLORS.get(stat, Palette.ON_SURFACE_VARIANT)
        self._label = ft.Text(STAT_LABELS.get(stat, stat), theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=colour, width=32)
        self._bar = ft.ProgressBar(value=0, bar_height=6, border_radius=Radius.PILL, color=colour, bgcolor=STAT_TRACK, expand=True)
        self._value = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE, width=40, text_align=ft.TextAlign.RIGHT)
        self._delta = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=colour, visible=False, width=44)
        self.controls = [self._label, self._bar, self._value, self._delta]
        self.set_value(value, delta_value)

    def set_value(self, value: int, delta_value: int | None = None) -> None:
        self._bar.value = max(0.0, min(1.0, value / STAT_MAX))
        self._value.value = str(value)
        if delta_value is not None and delta_value != value:
            pct = round((delta_value - value) / value * 100) if value else 0
            self._delta.value = f"{pct:+d}%"
            self._delta.visible = True
        else:
            self._delta.visible = False


class StatBlock(ft.Column):
    """Six stat bars in PokemonStats order.

    ``lazy`` defers building the bars until the block is first filled or read. Six bars
    are twenty-four Flet controls, so a grid of cards that hide their stats by default
    spent half its build time on controls nobody ever sees.
    """

    def __init__(self, stats: PokemonStats | None = None, *, spacing: int = Space.XS, lazy: bool = False) -> None:
        super().__init__(spacing=spacing, tight=True)
        self._bars: dict[str, StatBar] = {}
        if not lazy:
            self._build()
        if stats is not None:
            self.set_stats(stats)

    def _build(self) -> None:
        if self._bars:
            return
        self._bars = {stat: StatBar(stat) for stat in STAT_ORDER}
        self.controls = list(self._bars.values())

    @property
    def bars(self) -> dict[str, StatBar]:
        self._build()
        return self._bars

    def set_stats(self, stats: PokemonStats, effective: PokemonStats | None = None) -> None:
        for stat, bar in self.bars.items():
            bar.set_value(getattr(stats, stat), getattr(effective, stat) if effective else None)


class IdentityRow(ft.Row):
    """`avatar · name + form caption · type chips · trailing` — used in lists and dialogs."""

    def __init__(
        self,
        *,
        name: str = "",
        form: str | None = None,
        types: Sequence[str] = (),
        sprite_url: str | None = None,
        sprite_size: int = 40,
        trailing: ft.Control | None = None,
    ) -> None:
        super().__init__(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.sprite = Sprite(sprite_url, size=sprite_size)
        self._name = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._form = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._types = ft.Row(spacing=Space.XS, tight=True)
        self._trailing = ft.Row(spacing=Space.SM, tight=True, controls=[trailing] if trailing else [])
        self.controls = [
            self.sprite,
            ft.Column(spacing=2, tight=True, expand=True, controls=[self._name, self._form, self._types]),
            self._trailing,
        ]
        self.set(name=name, form=form, types=types, sprite_url=sprite_url)

    def set(self, *, name: str, form: str | None = None, types: Sequence[str] = (), sprite_url: str | None = None) -> None:
        self._name.value = name
        self._form.value = form or ""
        self._form.visible = bool(form) and form.lower() != "base"
        self._types.controls = [TypeChip(t, size="sm") for t in types]
        self.sprite.set_src(sprite_url)
        self.sprite.set_tooltip(name)


class SidePanel(ft.Container):
    """360px right panel with a title row and scrollable body; hairline on the left."""

    def __init__(self, title: str, *, on_close, width: int = 360, accent: str = Palette.SECONDARY) -> None:
        super().__init__()
        self.accent = accent
        self._title = ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self.body = ft.Column(spacing=Space.LG, expand=True, scroll=ft.ScrollMode.AUTO)
        self.content = ft.Column(
            spacing=Space.MD,
            expand=True,
            controls=[
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[self._title, ft.IconButton(icon=ft.Icons.CLOSE, icon_size=20, tooltip="Close (Esc)", on_click=lambda _e: on_close())],
                ),
                self.body,
            ],
        )
        self.width = width
        self.bgcolor = Palette.SURFACE_1
        self.border = ft.Border.only(left=ft.BorderSide(3, accent))
        self.padding = Space.PANEL_PADDING
        self.visible = False

    def set_title(self, title: str) -> None:
        self._title.value = title


def hover_tint(base: str | None, hovering: bool) -> str | None:
    """Hover surface for cards: base → surface-3."""
    return Palette.SURFACE_3 if hovering else base


__all__ = ["BstPill", "IdentityRow", "SidePanel", "StatBar", "StatBlock", "TypeChip", "hover_tint", "type_chips", "alpha"]
