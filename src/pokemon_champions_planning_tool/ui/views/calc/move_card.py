"""A move card: the move slot and its result in one type-coloured card.

Damaging moves show base power, the type multiplier, the damage range with a bar and the KO
text; clicking expands the description, the sixteen rolls, recoil/recovery, the bulk and power
benchmarks and Copy. Status moves with a known effect get an "Activate" toggle that applies it
to the calculation. In Doubles a spread move says it hits two targets (×0.75); one click
switches it to a single target (one foe left).
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ...components import StatusChip
from ...theme import IconSize, Palette, Radius, Space, alpha, type_color
from ...tasks import safe_update
from . import bench_view
from .benchmarks import Benchmarks
from .state import MoveResult

TARGETS_TIP = {
    2: "Spread move: hits both foes, ×0.75 damage each. Click for a single target (one foe fainted or protected).",
    1: "Spread move on a single target: full damage. Click to hit both foes again (×0.75).",
}

CATEGORY_ICONS = {"physical": ft.Icons.FITNESS_CENTER, "special": ft.Icons.AUTO_AWESOME, "status": ft.Icons.CHANGE_CIRCLE_OUTLINED}


def damage_colour(max_pct: float) -> str:
    if max_pct >= 100:
        return Palette.ERROR
    if max_pct >= 50:
        return Palette.WARNING
    if max_pct >= 25:
        return Palette.SECONDARY
    return Palette.ON_SURFACE_VARIANT


def effectiveness_label(mult: float | None) -> str:
    if mult is None:
        return ""
    return f"{mult:g}×"


class DamageBar(ft.Stack):
    def __init__(self) -> None:
        super().__init__()
        self._max = ft.ProgressBar(value=0, bar_height=6, color=Palette.OUTLINE, bgcolor=Palette.SURFACE_3)
        self._min = ft.ProgressBar(value=0, bar_height=6, color=Palette.OUTLINE, bgcolor=ft.Colors.TRANSPARENT)
        self.controls = [self._max, self._min]
        self.height = 6

    def set_range(self, min_pct: float, max_pct: float) -> None:
        colour = damage_colour(max_pct)
        self._max.value = min(1.0, max_pct / 100)
        self._max.color = alpha(colour, 0.4)
        self._min.value = min(1.0, min_pct / 100)
        self._min.color = colour


class MoveCard(ft.Container):
    def __init__(self, index: int, *, on_pick: Callable[[int], None], on_crit: Callable[[int], None], on_activate: Callable[[int], None], on_copy: Callable[[str], None],
                 on_targets: Callable[[int], None] | None = None, on_expand: Callable[[int], None] | None = None,
                 on_apply: Callable[[str, dict[str, int]], None] | None = None) -> None:
        super().__init__()
        self.index = index
        self.result: MoveResult | None = None
        self.expanded = False
        self._drawn: tuple | None = None
        self._on_copy = on_copy
        self._on_expand = on_expand
        self._on_apply = on_apply          # ("mine" | "theirs", points) from a benchmark
        self.benchmarks: Benchmarks | None = None
        self.bench_key: str | None = None  # the state the benchmarks were asked for
        self._bench_state = "idle"         # "idle" | "loading" | "ready"
        self._bench_names = ("You", "They")
        muted = Palette.ON_SURFACE_VARIANT
        self._name = ft.Text(f"Move {index + 1}…", theme_style=ft.TextThemeStyle.BODY_LARGE, weight=ft.FontWeight.W_600, color=Palette.DISABLED, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._category = ft.Icon(ft.Icons.ADD, size=IconSize.SM, color=Palette.DISABLED)
        self._bp = StatusChip("", "neutral")
        self._bp.visible = False
        self._eff = StatusChip("", "neutral")
        self._eff.visible = False
        self._targets_label = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE, weight=ft.FontWeight.W_600)
        self._targets = ft.Container(
            content=ft.Row(spacing=2, tight=True, controls=[ft.Icon(ft.Icons.GROUPS_2_OUTLINED, size=13, color=Palette.ON_SURFACE_VARIANT), self._targets_label]),
            padding=ft.Padding.symmetric(horizontal=6, vertical=1), border_radius=Radius.PILL, border=ft.Border.all(1, Palette.OUTLINE),
            ink=True, visible=False, on_click=lambda _e: on_targets(self.index) if on_targets else None,
        )
        self._effect = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=muted, visible=False, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._pct = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_SMALL, weight=ft.FontWeight.W_700, color=muted, text_align=ft.TextAlign.RIGHT)
        self._ko = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=muted, text_align=ft.TextAlign.RIGHT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, visible=False)
        self._bar = DamageBar()
        self._bar.visible = False
        self._activate = ft.Chip(label=ft.Text("Activate"), selected=False, show_checkmark=True, visible=False, on_select=lambda _e: on_activate(self.index))
        self._crit = ft.IconButton(icon=ft.Icons.FLASH_ON_OUTLINED, selected_icon=ft.Icons.FLASH_ON, icon_size=IconSize.SM, selected=False, tooltip="Critical hit",
                                   icon_color=muted, selected_icon_color=Palette.PRIMARY, on_click=lambda _e: on_crit(self.index), visible=False)
        self._edit = ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=IconSize.SM, tooltip="Choose move", icon_color=muted, on_click=lambda _e: on_pick(self.index))
        self._details = ft.Column(spacing=Space.SM, tight=True, visible=False, controls=[])
        self._name.expand = True
        # The second line (BP, effectiveness, damage, KO) only exists for a filled slot, so an
        # empty slot is a single slim "+ Move 1…" row.
        # The KO text has a line of its own: beside the chips it squeezed them to nothing.
        self._info = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, visible=False, controls=[
            ft.Row(spacing=Space.XS, run_spacing=Space.XS, wrap=True, expand=True, controls=[self._bp, self._eff, self._targets, self._effect]),
            self._pct,
        ])
        body = ft.Column(spacing=4, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._category, self._name, self._activate, self._crit, self._edit]),
            self._info,
            self._ko,
            self._bar,
            self._details,
        ])
        self.content = body
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS)
        self.border_radius = Radius.SM
        self.bgcolor = Palette.SURFACE_3
        self._set_border(Palette.OUTLINE, Palette.OUTLINE_VARIANT)
        self.ink = True
        self.on_click = lambda _e: self._clicked(on_pick)

    def _set_border(self, stripe: str, edge: str) -> None:
        """A thick type-coloured left edge (the "stripe") and a thin edge elsewhere."""
        self.border = ft.Border(left=ft.BorderSide(4, stripe), top=ft.BorderSide(1, edge), right=ft.BorderSide(1, edge), bottom=ft.BorderSide(1, edge))

    def _clicked(self, on_pick: Callable[[int], None]) -> None:
        if self.result is not None and self.result.ok:
            self.toggle()
        elif self._name.color == Palette.DISABLED:
            on_pick(self.index)

    def update_from(self, name: str | None, info, result: MoveResult | None, *, active: bool, effect: str | None, crit: bool) -> bool:
        """Draw this slot; returns False (and touches nothing) when it already shows this."""
        key = (name, info, result, active, effect, crit)
        if key == self._drawn:
            return False
        self._drawn = key
        self._apply(name, info, result, active=active, effect=effect, crit=crit)
        return True

    def _apply(self, name: str | None, info, result: MoveResult | None, *, active: bool, effect: str | None, crit: bool) -> None:
        self.result = result
        muted = Palette.ON_SURFACE_VARIANT
        if not name:
            self._name.value = f"Move {self.index + 1}…"
            self._name.color = Palette.DISABLED
            self._category.icon, self._category.color = ft.Icons.ADD, Palette.DISABLED
            self._info.visible = self._bp.visible = self._eff.visible = self._effect.visible = self._bar.visible = self._activate.visible = self._crit.visible = False
            self._targets.visible = False
            self._pct.value = self._ko.value = ""
            self._ko.visible = False
            self.bgcolor = Palette.SURFACE_3
            self._set_border(Palette.OUTLINE, Palette.OUTLINE_VARIANT)
            self._collapse()
            return
        type_name = (result.type if result is not None and result.type else (info.type if info is not None else None)) or None
        category = (result.category if result is not None and result.category else (info.category if info is not None else None)) or ""
        colour = type_color(type_name.lower()) if type_name and type_name != "???" else Palette.OUTLINE
        self._name.value = name
        self._name.color = Palette.ON_SURFACE
        self._info.visible = True
        self._category.icon = CATEGORY_ICONS.get(category.lower(), ft.Icons.HELP_OUTLINE)
        self._category.color = colour
        self.bgcolor = alpha(colour, 0.16)
        self._set_border(colour, alpha(colour, 0.45))
        is_status = category.lower() == "status" or effect is not None
        self._crit.visible = not is_status
        self._crit.selected = crit
        self._activate.visible = is_status and effect is not None
        self._activate.selected = active
        self._activate.label = ft.Text("Active" if active else "Activate")
        self._effect.visible = bool(effect) or (is_status and result is not None)
        self._effect.value = effect or ("Status move" if is_status else "")
        targets = result.targets if result is not None else None
        self._targets.visible = targets is not None
        if targets is not None:
            self._targets_label.value = "2 targets ×0.75" if targets == 2 else "1 target"
            self._targets.tooltip = TARGETS_TIP[targets]
            self._targets.bgcolor = alpha(Palette.SECONDARY, 0.2) if targets == 2 else None
        if result is None or not result.ok:
            self._bp.visible = self._eff.visible = self._bar.visible = False
            if result is not None and result.error and not is_status and effect is None:
                self._pct.value = "—"
                self._pct.color = muted
                self._ko.value = result.error
            else:
                self._pct.value = self._ko.value = ""
            self._ko.visible = bool(self._ko.value)
            self._collapse()
            return
        self._bp.visible = result.bp is not None
        self._bp.set(f"{result.bp:g} BP", "neutral")
        eff = result.effectiveness
        self._eff.visible = eff is not None and eff != 1.0
        if eff is not None:
            self._eff.set(effectiveness_label(eff), "error" if eff > 1 else "neutral")
        self._pct.value = f"{result.min_pct:g}–{result.max_pct:g}%"
        self._pct.color = damage_colour(result.max_pct)
        self._ko.value = result.ko_text or f"{result.min_dmg}–{result.max_dmg} HP"
        self._ko.color = Palette.ERROR if "OHKO" in (result.ko_text or "") else muted
        self._ko.visible = True
        self._bar.visible = True
        self._bar.set_range(result.min_pct, result.max_pct)
        if self.expanded:
            self._fill_details()

    def _collapse(self) -> None:
        self.expanded = False
        self._details.visible = False
        self._details.controls = []
        self._bench_state = "idle"
        self.benchmarks = None
        self.bench_key = None

    def _fill_details(self) -> None:
        r = self.result
        if r is None:
            return
        lines: list[ft.Control] = [
            ft.Text(r.description, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE, selectable=True),
            ft.Row(spacing=Space.XS, wrap=True, controls=[StatusChip(str(v), "neutral") for v in r.rolls]),
        ]
        if r.recoil:
            lines.append(ft.Text(r.recoil, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.WARNING))
        if r.recovery:
            lines.append(ft.Text(r.recovery, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.SUCCESS))
        if self._on_expand is not None:
            lines.append(self._bench_block())
        lines.append(ft.Row(alignment=ft.MainAxisAlignment.END, controls=[ft.TextButton("Copy", icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._on_copy(r.description))]))
        self._details.controls = lines

    # -- benchmarks ----------------------------------------------------------------------------

    def set_benchmarks(self, value: Benchmarks | None, *, loading: bool = False, names: tuple[str, str] = ("You", "They")) -> None:
        """The view's answer for this card (or that it is on its way); redraws the details.
        ``names`` are the attacker's and the target's, for the lines."""
        self.benchmarks = value
        self._bench_state = "loading" if loading else "ready"
        self._bench_names = names
        if self.expanded:
            self._fill_details()
            safe_update(self._details)

    def _bench_block(self) -> ft.Control:
        title = bench_view.heading()
        if self._bench_state != "ready":
            return bench_view.loading(title)
        mine, theirs = self._bench_names
        return ft.Column(spacing=2, tight=True, controls=[title, *bench_view.rows(self.benchmarks, mine=mine, theirs=theirs, on_apply=self._on_apply)])

    def toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            if self._on_expand is not None:
                self._on_expand(self.index)     # may answer at once from the cache
            self._fill_details()
        else:
            self._details.controls = []
        self._details.visible = self.expanded
        safe_update(self)
