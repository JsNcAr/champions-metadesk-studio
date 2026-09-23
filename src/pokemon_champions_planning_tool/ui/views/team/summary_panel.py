"""Team analysis panel: Overview, level-50 Stats, Coverage and Roles tabs."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.type_chart import TYPES
from ....domain.stat_calc import nature_multiplier
from ....domain.team_roles import RoleCheck
from ...components import SectionHeader, Sprite
from ...components.pokemon import SidePanel, StatBlock, TypeChip
from ...tasks import is_mounted
from ...theme import Accent, IconSize, Palette, Radius, STAT_COLORS, Space, alpha
from .status import check_chip
from .summary import SlotModel, TeamSummary

_CELL = 14


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


TABS: tuple[tuple[str, str, str], ...] = (
    ("overview", "Health", ft.Icons.DASHBOARD_OUTLINED),     # short labels: four fit the 320px panel
    ("stats", "Stats", ft.Icons.BAR_CHART),
    ("coverage", "Types", ft.Icons.GRID_ON),
    ("roles", "Roles", ft.Icons.CHECKLIST),
)
_TAB_TIPS = {"overview": "Health checks and average stats", "stats": "Level-50 stats, sortable (speed order)",
             "coverage": "Defensive and offensive type coverage", "roles": "Speed control, Fake Out, Intimidate…"}
_STAT_COLUMNS: tuple[tuple[str, str], ...] = (("hp", "HP"), ("attack", "Atk"), ("defense", "Def"), ("special_attack", "SpA"), ("special_defense", "SpD"), ("speed", "Spe"))
_NAME_W = 92
_STAT_W = 36


class SummaryPanel(SidePanel):
    """Team analysis in four tabs, each built when it is first shown and rebuilt only when
    shown after the team changed: Overview (avatars, health, average stats), Stats (level-50
    battle stats, sortable), Coverage (defensive and offensive grids), Roles (checklist)."""

    def __init__(self, *, on_close: Callable[[], None], on_focus_slot: Callable[[int], None]) -> None:
        super().__init__("Team analysis", on_close=on_close, accent=Accent.TEAMS)
        self._on_focus_slot = on_focus_slot
        self.tab = "overview"
        self._stale: set[str] = {key for key, _l, _i in TABS}
        self._slots: list[SlotModel] = []
        self._summary: TeamSummary | None = None
        self._roles: list[RoleCheck] = []
        self._focused: int | None = None
        self._sort: str | None = None          # stat key; None keeps slot order
        self._coverage_mode = "defense"

        self._tabs = ft.SegmentedButton(
            segments=[ft.Segment(value=key, label=ft.Text(label), tooltip=_TAB_TIPS[key]) for key, label, _icon in TABS],
            selected=[self.tab], show_selected_icon=False, on_change=lambda e: self.show_tab((e.control.selected or ["overview"])[0]),
        )
        # -- overview
        self._avatars = ft.Row(spacing=Space.SM, alignment=ft.MainAxisAlignment.CENTER)
        self._stats = StatBlock()
        self._stats_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._health = ft.Column(spacing=Space.XS, tight=True)
        self._overview = ft.Column(spacing=Space.LG, tight=True, controls=[
            self._avatars,
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Health", accent=Accent.TEAMS), self._health]),
            ft.Column(spacing=Space.SM, tight=True, controls=[SectionHeader("Average base stats", accent=Accent.TEAMS), self._stats_caption, self._stats]),
        ])
        # -- battle stats
        self._battle = ft.Column(spacing=Space.XS, tight=True)
        self._battle_view = ft.Column(spacing=Space.SM, tight=True, controls=[
            SectionHeader("Level 50 stats", accent=Accent.TEAMS),
            ft.Text("From each spread and nature, before items. Click a column to sort; Spe sorts by speed.",
                    theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._battle,
        ])
        # -- coverage
        self._grid = ft.Column(spacing=2, tight=True)
        self._offense_grid = ft.Column(spacing=2, tight=True)
        self._uncovered = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._coverage_switch = ft.SegmentedButton(
            segments=[ft.Segment(value="defense", label=ft.Text("Defense")), ft.Segment(value="offense", label=ft.Text("Offense"))],
            selected=["defense"], show_selected_icon=False, on_change=lambda e: self._set_coverage((e.control.selected or ["defense"])[0]),
        )
        self._defense_view = ft.Column(spacing=Space.SM, tight=True, controls=[
            ft.Text("How each attacking type hits your six.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._grid, self._legend()])
        self._offense_view = ft.Column(spacing=Space.SM, tight=True, visible=False, controls=[
            ft.Text("The best hit your six have on each defending type.", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._offense_grid, self._uncovered, self._offense_legend()])
        self._coverage = ft.Column(spacing=Space.MD, tight=True, controls=[self._coverage_switch, self._defense_view, self._offense_view])
        # -- roles
        self._role_rows = ft.Column(spacing=Space.SM, tight=True)
        self._roles_view = ft.Column(spacing=Space.SM, tight=True, controls=[
            SectionHeader("Roles", accent=Accent.TEAMS),
            ft.Text("What the team brings, from its moves, abilities and items. A missing role is a choice, not an error.",
                    theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            self._role_rows,
        ])
        self._views = {"overview": self._overview, "stats": self._battle_view, "coverage": self._coverage, "roles": self._roles_view}
        self._host = ft.Container(content=self._overview)
        self.body.controls = [self._tabs, self._host]
        self.visible = True

    # -- tabs ------------------------------------------------------------------------------------------

    def show_tab(self, tab: str) -> None:
        if tab not in self._views:
            return
        self.tab = tab
        self._tabs.selected = [tab]
        self._host.content = self._views[tab]
        self._render(tab)
        if is_mounted(self):
            self.update()

    def _set_coverage(self, mode: str) -> None:
        self._coverage_mode = mode
        self._coverage_switch.selected = [mode]
        self._defense_view.visible = mode == "defense"
        self._offense_view.visible = mode == "offense"
        if is_mounted(self._coverage):
            self._coverage.update()

    def update_from(self, slots: list[SlotModel], summary: TeamSummary, *, focused: int | None = None, roles: list[RoleCheck] | None = None) -> None:
        """New data: only the tab on screen is rebuilt now; the others when shown."""
        self._slots, self._summary, self._focused = list(slots), summary, focused
        if roles is not None:
            self._roles = roles
        self._stale = {key for key, _l, _i in TABS}
        self._render(self.tab)

    def _render(self, tab: str) -> None:
        if tab not in self._stale or self._summary is None:
            return
        self._stale.discard(tab)
        {"overview": self._render_overview, "stats": self._render_stats, "coverage": self._render_coverage, "roles": self._render_roles}[tab]()

    # -- overview -------------------------------------------------------------------------------------

    def _render_overview(self) -> None:
        slots, summary, focused = self._slots, self._summary, self._focused
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
            self._avatars.controls.append(ft.Container(content=sprite, on_click=lambda _e, p=slot.position: self._on_focus_slot(p)))
        self._stats.set_stats(summary.averages)
        if summary.filled:
            self._stats_caption.value = f"Average of {summary.filled} · totals shown in tooltips"
            for stat, bar in self._stats.bars.items():
                bar.tooltip = f"{stat}: total {getattr(summary.totals, stat)}"
        else:
            self._stats_caption.value = "Assign Pokémon to see team stats"
        self._health.controls = [
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                check_chip(c, tooltip=False),
                ft.Text(c.detail, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True),
            ])
            for c in summary.checks
        ] or [ft.Text("No team selected", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]

    # -- level-50 stats ---------------------------------------------------------------------------------

    def sort_by(self, stat: str | None) -> None:
        self._sort = None if stat == self._sort else stat
        self._stale.add("stats")
        self._render("stats")
        if is_mounted(self._battle):
            self._battle.update()

    def battle_rows(self) -> list[tuple[SlotModel, object]]:
        rows = [(s, s.battle_stats) for s in self._slots if s.filled and s.battle_stats is not None]
        if self._sort:
            rows.sort(key=lambda r: getattr(r[1], self._sort), reverse=True)
        return rows

    def _render_stats(self) -> None:
        rows = self.battle_rows()
        if not rows:
            self._battle.controls = [ft.Text("Assign Pokémon to see their stats", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
            return

        def header(key: str, label: str) -> ft.Control:
            active = key == self._sort
            return ft.Container(width=_STAT_W, alignment=ft.Alignment.CENTER_RIGHT, ink=True, on_click=lambda _e, k=key: self.sort_by(k),
                                tooltip=f"Sort by {label}" if not active else "Back to slot order",
                                content=ft.Text(label + (" ▼" if active else ""), theme_style=ft.TextThemeStyle.LABEL_SMALL,
                                                color=STAT_COLORS.get(key, Palette.ON_SURFACE_VARIANT), weight=ft.FontWeight.W_600))

        lines: list[ft.Control] = [ft.Row(spacing=0, controls=[ft.Container(width=_NAME_W), *(header(k, label) for k, label in _STAT_COLUMNS)])]
        totals = {k: 0 for k, _l in _STAT_COLUMNS}
        for slot, stats in rows:
            cells: list[ft.Control] = []
            for key, _label in _STAT_COLUMNS:
                value = getattr(stats, key)
                totals[key] += value
                try:
                    mult = nature_multiplier((slot.member.nature or "hardy").lower(), key) if key != "hp" else 1.0
                except ValueError:
                    mult = 1.0
                colour = Palette.SUCCESS if mult > 1 else (Palette.ERROR if mult < 1 else Palette.ON_SURFACE)
                cells.append(ft.Text(str(value), width=_STAT_W, text_align=ft.TextAlign.RIGHT, theme_style=ft.TextThemeStyle.BODY_SMALL, color=colour,
                                     weight=ft.FontWeight.W_600 if mult != 1 else None))
            name = slot.form.label if slot.form is not None and slot.form.is_mega else slot.entry.pokemon.display_name
            lines.append(ft.Container(
                ink=True, on_click=lambda _e, p=slot.position: self._on_focus_slot(p), border_radius=Radius.SM, tooltip=f"{name} · {slot.spread_summary}",
                content=ft.Row(spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Row(width=_NAME_W, spacing=Space.XS, controls=[
                        Sprite(slot.form.sprite_url if slot.form else None, size=24),
                        ft.Text(name, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    ]),
                    *cells,
                ]),
            ))
        n = len(rows)
        lines.append(ft.Divider(height=1))
        lines.append(ft.Row(spacing=0, controls=[
            ft.Text("Average", width=_NAME_W, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
            *(ft.Text(str(round(totals[k] / n)), width=_STAT_W, text_align=ft.TextAlign.RIGHT, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)
              for k, _l in _STAT_COLUMNS),
        ]))
        self._battle.controls = lines

    # -- roles -------------------------------------------------------------------------------------------

    def _render_roles(self) -> None:
        if not self._roles:
            self._role_rows.controls = [ft.Text("Assign Pokémon and moves to see the team's roles", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
            return
        rows: list[ft.Control] = []
        for check in self._roles:
            ok = check.status == "ok"
            icon = ft.Icon(ft.Icons.CHECK_CIRCLE if ok else (ft.Icons.INFO_OUTLINE if check.status == "info" else ft.Icons.RADIO_BUTTON_UNCHECKED),
                           size=IconSize.MD, color=Palette.SUCCESS if ok else (Palette.INFO if check.status == "info" else Palette.DISABLED))
            detail = ", ".join(check.providers) if check.providers and check.key != "protect" else check.note
            if check.key == "protect" and check.providers:
                detail = check.note
            rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                icon,
                ft.Column(spacing=0, tight=True, expand=True, controls=[
                    ft.Text(check.label, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE if ok else Palette.ON_SURFACE_VARIANT),
                    ft.Text(detail, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
                ]),
            ]))
        self._role_rows.controls = rows

    # -- coverage ----------------------------------------------------------------------------------------

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

    def _render_coverage(self) -> None:
        slots, summary = self._slots, self._summary
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

