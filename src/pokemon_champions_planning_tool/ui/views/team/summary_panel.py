"""Team summary panel: six avatars, average stat bars, the defensive grid, health."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.type_chart import TYPES
from ...components import SectionHeader, Sprite, StatusChip
from ...components.pokemon import SidePanel, StatBlock, TypeChip
from ...theme import Accent, Palette, Radius, Space, alpha
from .summary import SlotModel, TeamSummary

_CELL = 14
_STATUS_TONE = {"ok": "success", "warn": "warning", "error": "error", "info": "info"}
_STATUS_ICON = {"ok": ft.Icons.CHECK, "warn": ft.Icons.WARNING_AMBER_OUTLINED, "error": ft.Icons.ERROR_OUTLINE, "info": ft.Icons.INFO_OUTLINE}


def _cell_colour(mult: float) -> str | None:
    if mult >= 4.0:
        return Palette.ERROR
    if mult >= 2.0:
        return alpha(Palette.ERROR, 0.6)
    if mult == 0.0:
        return Palette.SECONDARY
    if mult <= 0.25:
        return Palette.SUCCESS
    if mult < 1.0:
        return alpha(Palette.SUCCESS, 0.6)
    return None


class SummaryPanel(SidePanel):
    def __init__(self, *, on_close: Callable[[], None], on_focus_slot: Callable[[int], None]) -> None:
        super().__init__("Team summary", on_close=on_close, accent=Accent.TEAMS)
        self._on_focus_slot = on_focus_slot
        self._avatars = ft.Row(spacing=Space.SM, alignment=ft.MainAxisAlignment.CENTER)
        self._stats = StatBlock()
        self._stats_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._grid = ft.Column(spacing=2, tight=True)
        self._offense_grid = ft.Column(spacing=2, tight=True)
        self._uncovered = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._health = ft.Column(spacing=Space.XS, tight=True)
        self.body.controls = [
            self._avatars,
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Stats", accent=Accent.TEAMS), self._stats_caption, self._stats]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Defensive coverage", accent=Accent.TEAMS), self._grid, self._legend()]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Offensive coverage", accent=Accent.TEAMS), self._offense_grid, self._uncovered, self._offense_legend()]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Health", accent=Accent.TEAMS), self._health]),
        ]
        self.visible = True

    @staticmethod
    def _legend() -> ft.Row:
        def swatch(colour, label):
            return ft.Row(spacing=4, tight=True, controls=[ft.Container(width=10, height=10, bgcolor=colour, border_radius=2), ft.Text(label, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)])
        return ft.Row(spacing=Space.SM, wrap=True, controls=[swatch(Palette.ERROR, "weak"), swatch(alpha(Palette.SUCCESS, 0.6), "resist"), swatch(Palette.SECONDARY, "immune")])

    @staticmethod
    def _offense_legend() -> ft.Row:
        def swatch(colour, label):
            return ft.Row(spacing=4, tight=True, controls=[ft.Container(width=10, height=10, bgcolor=colour, border_radius=2), ft.Text(label, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)])
        return ft.Row(spacing=Space.SM, wrap=True, controls=[swatch(Palette.SUCCESS, "super-effective"), swatch(alpha(Palette.OUTLINE, 0.6), "neutral"), swatch(Palette.WARNING, "resisted"), swatch(Palette.ERROR, "immune")])

    @staticmethod
    def _offense_colour(m: float | None) -> str:
        if m is None:
            return alpha(Palette.OUTLINE, 0.25)
        if m > 1.0:
            return Palette.SUCCESS
        if m == 1.0:
            return alpha(Palette.OUTLINE, 0.6)
        if m == 0.0:
            return Palette.ERROR
        return Palette.WARNING

    def update_from(self, slots: list[SlotModel], summary: TeamSummary, *, focused: int | None = None) -> None:
        self._avatars.controls = []
        for slot in slots:
            if slot.filled and slot.form is not None:
                ring = "planned" if slot.is_planned else ("mega" if slot.form.is_mega else "type")
                sprite = Sprite(slot.form.sprite_url, size=40, ring="selected" if slot.position == focused else ring,
                                primary_type=slot.form.types[0] if slot.form.types else None,
                                tooltip=f"Slot {slot.position} · {slot.entry.pokemon.display_name}", badge_number=slot.position)
            else:
                sprite = ft.Container(width=40, height=40, border_radius=Radius.PILL, border=ft.Border.all(1, Palette.OUTLINE), alignment=ft.Alignment.CENTER,
                                      content=ft.Text(str(slot.position), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.DISABLED))
            holder = ft.Container(content=sprite, on_click=lambda _e, p=slot.position: self._on_focus_slot(p))
            self._avatars.controls.append(holder)

        if summary.filled:
            self._stats.set_stats(summary.averages)
            self._stats_caption.value = f"Average of {summary.filled} · totals shown in tooltips"
            for stat, bar in self._stats.bars.items():
                bar.tooltip = f"{stat}: total {getattr(summary.totals, stat)}"
        else:
            self._stats.set_stats(summary.averages)
            self._stats_caption.value = "Assign Pokémon to see team stats"

        rows: list[ft.Control] = []
        for atk in TYPES:
            mults = summary.matrix.get(atk, [1.0] * 6)
            weak, resist, immune = summary.weakness.get(atk, (0, 0, 0))
            cells = [
                ft.Container(width=_CELL, height=_CELL, border_radius=2, bgcolor=_cell_colour(m) or alpha(Palette.OUTLINE, 0.25),
                             tooltip=f"×{m:g}" if slots[i].filled else None)
                for i, m in enumerate(mults[:6])
            ]
            caption_bits = []
            if weak:
                caption_bits.append(f"{weak}W")
            if resist:
                caption_bits.append(f"{resist}R")
            if immune:
                caption_bits.append(f"{immune}I")
            rows.append(
                ft.Row(
                    spacing=Space.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(content=TypeChip(atk, size="sm"), width=72),
                        ft.Row(spacing=3, tight=True, controls=cells),
                        ft.Text(" · ".join(caption_bits), theme_style=ft.TextThemeStyle.BODY_SMALL,
                                color=Palette.ERROR if weak >= 3 else Palette.ON_SURFACE_VARIANT),
                    ],
                )
            )
        self._grid.controls = rows

        offense_rows: list[ft.Control] = []
        for d in TYPES:
            mults = summary.offense.get(d, [None] * 6)
            super_, _neutral, _poor = summary.offense_counts.get(d, (0, 0, 0))
            cells = [
                ft.Container(width=_CELL, height=_CELL, border_radius=2, bgcolor=self._offense_colour(m),
                             tooltip=(f"×{m:g}" if m is not None else "no damaging moves") if slots[i].filled else None)
                for i, m in enumerate(mults[:6])
            ]
            caption = f"{super_} SE" if super_ else ("uncovered" if summary.has_moves else "")
            offense_rows.append(
                ft.Row(
                    spacing=Space.SM,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Container(content=TypeChip(d, size="sm"), width=72),
                        ft.Row(spacing=3, tight=True, controls=cells),
                        ft.Text(caption, theme_style=ft.TextThemeStyle.BODY_SMALL,
                                color=Palette.WARNING if (summary.has_moves and not super_) else Palette.ON_SURFACE_VARIANT),
                    ],
                )
            )
        self._offense_grid.controls = offense_rows
        if not summary.has_moves:
            self._uncovered.value = "Assign damaging moves to see what the team hits"
        elif summary.uncovered:
            self._uncovered.value = "Not hit super-effectively by anyone: " + ", ".join(t.capitalize() for t in summary.uncovered)
        else:
            self._uncovered.value = "Every type is hit super-effectively by at least one slot"

        self._health.controls = [
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                StatusChip(c.label, _STATUS_TONE[c.status], icon=_STATUS_ICON[c.status]),
                ft.Text(c.detail, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True),
            ])
            for c in summary.checks
        ] or [ft.Text("No team selected", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
