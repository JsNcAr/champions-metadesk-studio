"""Results: one row per move in each direction, with a damage bar and the KO text; a row expands
into the full description, the sixteen rolls, recoil and recovery, and a Copy button."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...components import EmptyState, StatusChip
from ...components.pokemon import TypeChip
from ...components.section import SectionHeader
from ...theme import IconSize, Palette, Radius, Space, alpha
from .state import CalcResults, MoveResult

CATEGORY_ICONS = {"physical": ft.Icons.FITNESS_CENTER, "special": ft.Icons.AUTO_AWESOME, "status": ft.Icons.CHANGE_CIRCLE_OUTLINED}


def damage_colour(max_pct: float) -> str:
    if max_pct >= 100:
        return Palette.ERROR
    if max_pct >= 50:
        return Palette.WARNING
    if max_pct >= 25:
        return Palette.SECONDARY
    return Palette.OUTLINE


class DamageBar(ft.Stack):
    """Two bars: the maximum roll translucent, the minimum solid, in the damage colour."""

    def __init__(self, min_pct: float, max_pct: float) -> None:
        super().__init__()
        colour = damage_colour(max_pct)
        self.controls = [
            ft.ProgressBar(value=min(1.0, max_pct / 100), bar_height=8, color=alpha(colour, 0.4), bgcolor=Palette.SURFACE_3),
            ft.ProgressBar(value=min(1.0, min_pct / 100), bar_height=8, color=colour, bgcolor=ft.Colors.TRANSPARENT),
        ]
        self.height = 8


class ResultRow(ft.Container):
    def __init__(self, result: MoveResult, *, on_copy: Callable[[str], None]) -> None:
        super().__init__()
        self.result = result
        self._on_copy = on_copy
        self.expanded = False
        r = result
        muted = Palette.ON_SURFACE_VARIANT
        head_controls: list[ft.Control] = [
            TypeChip(r.type.lower(), size="sm") if r.type and r.type != "???" else ft.Container(width=8),
            ft.Icon(CATEGORY_ICONS.get((r.category or "").lower(), ft.Icons.HELP_OUTLINE), size=IconSize.SM, color=muted),
            ft.Text(r.name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE if r.ok else muted, width=150, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ]
        if r.ok:
            head_controls += [
                ft.Text(f"{r.min_dmg}–{r.max_dmg}", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, width=76, text_align=ft.TextAlign.RIGHT),
                ft.Text(f"{r.min_pct:g}–{r.max_pct:g}%", theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=damage_colour(r.max_pct), width=104, text_align=ft.TextAlign.RIGHT),
                ft.Container(content=DamageBar(r.min_pct, r.max_pct), expand=True, padding=ft.Padding.symmetric(horizontal=Space.SM)),
                ft.Text(r.ko_text or "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ERROR if "OHKO" in (r.ko_text or "") else muted, width=230, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=r.ko_text),
                ft.Icon(ft.Icons.EXPAND_MORE, size=IconSize.SM, color=muted),
            ]
        else:
            head_controls += [ft.Text(r.error or "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=muted, expand=True)]
        self._head = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=head_controls)
        self._details = ft.Column(spacing=Space.SM, tight=True, visible=False, controls=[])
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[self._head, self._details])
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM)
        self.border_radius = Radius.SM
        self.bgcolor = Palette.SURFACE_2
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        if r.ok:
            self.ink = True
            self.on_click = lambda _e: self.toggle()

    def toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded and not self._details.controls:
            r = self.result
            lines: list[ft.Control] = [
                ft.Text(r.description, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, selectable=True),
                ft.Row(spacing=Space.XS, wrap=True, controls=[StatusChip(str(v), "neutral") for v in r.rolls]),
            ]
            if r.bp is not None:
                lines.append(ft.Text(f"Base power {r.bp:g}", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
            if r.recoil:
                lines.append(ft.Text(r.recoil, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.WARNING))
            if r.recovery:
                lines.append(ft.Text(r.recovery, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.SUCCESS))
            lines.append(ft.Row(alignment=ft.MainAxisAlignment.END, controls=[ft.TextButton("Copy", icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._on_copy(r.description))]))
            self._details.controls = lines
        self._details.visible = self.expanded
        self.bgcolor = Palette.SURFACE_3 if self.expanded else Palette.SURFACE_2
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass


class ResultsList(ft.Column):
    def __init__(self, *, on_copy: Callable[[str], None], accent: str) -> None:
        super().__init__(spacing=Space.MD, tight=True)
        self._on_copy = on_copy
        self._accent = accent
        self.rows: list[ResultRow] = []
        self.empty = EmptyState(ft.Icons.CALCULATE_OUTLINED, "Pick two Pokémon", "Choose a species on each side and give them moves to see the damage both ways.")
        self.controls = [self.empty]

    def update_from(self, results: CalcResults) -> None:
        self.rows = []
        sections: list[ft.Control] = []
        for title, rows in ((f"{results.left_name} → {results.right_name}", results.left_vs_right), (f"{results.right_name} → {results.left_name}", results.right_vs_left)):
            if not rows:
                continue
            sections.append(SectionHeader(title, accent=self._accent))
            for r in rows:
                row = ResultRow(r, on_copy=self._on_copy)
                self.rows.append(row)
                sections.append(row)
        self.controls = sections or [self.empty]
        try:
            if self.page is not None:
                self.update()
        except RuntimeError:
            pass

    def collapse_all(self) -> bool:
        changed = False
        for row in self.rows:
            if row.expanded:
                row.toggle()
                changed = True
        return changed
