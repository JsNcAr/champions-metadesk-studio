"""Compare two teams side by side: rosters, average stats, health and coverage (FR-13)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import flet as ft

from ....components import Sprite
from ....components.pokemon import StatBlock
from ....tasks import is_mounted
from ....theme import Palette, Radius, Space
from ..status import check_chip
from ..store import TeamStore
from ..summary import EMPTY_SUMMARY, SlotModel, TeamSummary



class _TeamColumn(ft.Container):
    def __init__(self) -> None:
        super().__init__()
        self._name = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._avatars = ft.Row(spacing=Space.XS, tight=True)
        self._stats = StatBlock()
        self._caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._checks = ft.Column(spacing=Space.XS, tight=True)
        self._coverage = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._weak = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[self._name, self._avatars, self._caption, self._stats, self._checks, self._coverage, self._weak])
        self.bgcolor = Palette.SURFACE_2
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.border_radius = Radius.MD
        self.padding = Space.MD
        self.expand = True

    def update_from(self, name: str, slots: list[SlotModel], summary: TeamSummary) -> None:
        self._name.value = name or "—"
        self._avatars.controls = [
            Sprite(s.form.sprite_url, size=32, ring="mega" if s.form.is_mega else "type", primary_type=s.form.types[0] if s.form.types else None, tooltip=s.entry.pokemon.display_name)
            if s.filled and s.form is not None else
            ft.Container(width=32, height=32, border_radius=Radius.PILL, border=ft.Border.all(1, Palette.OUTLINE))
            for s in slots
        ]
        self._caption.value = f"{summary.filled}/6 · averages" if summary.filled else "Empty team"
        self._stats.set_stats(summary.averages)
        for stat, bar in self._stats.bars.items():
            bar.tooltip = f"{stat}: total {getattr(summary.totals, stat)}"
        self._checks.controls = [check_chip(c) for c in summary.checks]
        if not summary.has_moves:
            self._coverage.value = "Coverage: no damaging moves assigned"
        elif summary.uncovered:
            self._coverage.value = "Uncovered: " + ", ".join(t.capitalize() for t in summary.uncovered)
        else:
            self._coverage.value = "Coverage: every type hit super-effectively"
        weak = sorted(((w, t) for t, (w, _r, _i) in summary.weakness.items() if w >= 2), reverse=True)[:4]
        self._weak.value = ("Shared weaknesses: " + ", ".join(f"{t.capitalize()} ×{w}" for w, t in weak)) if weak else "No type hits two or more members super-effectively"


class CompareDialog(ft.AlertDialog):
    def __init__(self, store: TeamStore, *, on_close: Callable[[], None], other_id: UUID | None = None) -> None:
        super().__init__(modal=False, scrollable=True)
        self.store = store
        self._left, self._right = _TeamColumn(), _TeamColumn()
        others = [t for t in store.teams if t.team_id != store.active_team_id]
        self._picker = ft.Dropdown(
            label="Compare with", width=260, dense=True,
            options=[ft.DropdownOption(key=str(t.team_id), text=f"{t.name} · {t.filled}/6") for t in others],
            value=None,
            on_select=lambda e: self.set_other(UUID(e.control.value)) if e.control.value else None,
        )
        self.title = ft.Text("Compare teams")
        self.content = ft.Container(
            width=860,
            content=ft.Column(spacing=Space.MD, tight=True, controls=[
                self._picker,
                ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self._left, self._right]),
            ]),
        )
        self.actions = [ft.TextButton("Close", on_click=lambda _e: on_close())]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._left.update_from(store.active_team_name, store.slots, store.summary)
        # The team picked in the library, or the first other one; comparing a team with
        # itself falls back to the first other team.
        wanted = other_id if other_id is not None and any(t.team_id == other_id for t in others) else (others[0].team_id if others else None)
        if wanted is not None:
            self._picker.value = str(wanted)
            self.set_other(wanted)
        else:
            self._right.update_from("No other team", [SlotModel(p) for p in range(1, 7)], EMPTY_SUMMARY)
            self._right._caption.value = "Create a second team to compare"

    def set_other(self, team_id: UUID) -> None:
        name, slots, summary = self.store.summary_for(team_id)
        self._right.update_from(name, slots, summary)
        if is_mounted(self):
            self.update()


__all__ = ["CompareDialog"]
