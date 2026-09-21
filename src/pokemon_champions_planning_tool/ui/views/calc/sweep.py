"""Right rail: every Champions species classified against the attacker (Threat, Wall, Neutral,
Mitigated, Crushed), searchable, with tournament sets for their moves."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite, StatusChip
from ...components.inputs import SEARCH_FIELD_STYLE
from ...components.section import SectionHeader
from ...tasks import Debouncer, is_mounted
from ...theme import IconSize, Palette, Radius, Space, alpha
from .state import SWEEP_CLASSES, SweepEntry
from .store import CalcStore

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
CLASS_BORDER = {
    "threat": ft.Border.all(1, alpha(Palette.ERROR, 0.40)),
    "wall": ft.Border.all(1, alpha(Palette.WARNING, 0.40)),
    "neutral": ft.Border.all(1, Palette.OUTLINE_VARIANT),
    "mitigated": ft.Border.all(1, alpha(Palette.SECONDARY, 0.35)),
    "crushed": ft.Border.all(1, alpha(Palette.SUCCESS, 0.40)),
}
_INITIAL_LIMIT = 40
_PAGE_SIZE = 40


class SweepCard(ft.Container):
    def __init__(self, entry: SweepEntry, *, on_pick: Callable[[SweepEntry], None]) -> None:
        super().__init__()
        e = entry
        yours = f"{e.your_best.name} {e.your_best.min_pct:g}–{e.your_best.max_pct:g}%" if e.your_best else "no damage"
        theirs_base = f"{e.their_best.name} {e.their_best.min_pct:g}–{e.their_best.max_pct:g}%" if e.their_best else ("no damaging set" if e.preset else "moves unknown")
        theirs = f"{theirs_base} · {e.usage_count} teams" if e.usage_count > 0 else theirs_base
        # Same convention as the panels' speed chip: ▲ = you move first.
        speed = ft.Text(f"Spe {e.speed} {'▲' if e.faster else '▼'}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.SUCCESS if e.faster else Palette.ERROR,
                        tooltip="You move first" if e.faster else "They move first")
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            Sprite(get_pokemon_sprite_url(e.canonical_id), size=36),
            ft.Column(spacing=1, tight=True, expand=True, controls=[
                ft.Row(spacing=Space.XS, tight=True, controls=[
                    ft.Text(e.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                    speed,
                ]),
                ft.Text(f"You: {yours}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"Them: {theirs}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ]),
            StatusChip(dict(SWEEP_CLASSES)[e.klass], CLASS_TONES[e.klass], tooltip=CLASS_HELP[e.klass]),  # type: ignore[arg-type]
        ])
        self.padding = ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS)
        self.border_radius = Radius.SM
        self.bgcolor = CLASS_BG.get(e.klass, Palette.SURFACE_2)
        self.border = CLASS_BORDER.get(e.klass, ft.Border.all(1, Palette.OUTLINE_VARIANT))
        self.ink = True
        self.tooltip = f"Load as defender · {e.usage_count} tournament teams" if e.usage_count > 0 else "Load as defender"
        self.on_click = lambda _e: on_pick(entry)


class SweepPanel(ft.Container):
    def __init__(self, *, store: CalcStore, accent: str, on_pick: Callable[[SweepEntry], None]) -> None:
        super().__init__()
        self.store = store
        self._on_pick = on_pick
        self.query = ""
        self.klass: str | None = None
        self._limit = _INITIAL_LIMIT
        self._presets = ft.Switch(label="Tournament sets", value=store.sweep_presets, tooltip="Give each opponent its four most used moves from the stored rosters",
                                  on_change=lambda e: store.set_sweep_presets(bool(e.control.value)))
        self._sort = ft.Dropdown(
            label="Sort by",
            dense=True,
            text_size=12,
            options=self._sort_options(),
            value=self._current_sort_value(),
            tooltip="Sort rival opponents",
            on_select=lambda e: self._on_sort_changed(e.control.value),
        )
        self._search = ft.TextField(hint_text="Search opponent…", dense=True, prefix_icon=ft.Icons.SEARCH, **SEARCH_FIELD_STYLE, on_change=lambda e: self._query_typed(e.control.value or ""))
        self._query_later: Debouncer | None = None
        self._chips: dict[str | None, ft.Chip] = {}
        chips: list[ft.Control] = []
        for key, label in ((None, "All"), *SWEEP_CLASSES):
            chip = ft.Chip(label=ft.Text(label), selected=key is None, show_checkmark=False, on_select=lambda _e, key=key: self._set_class(key))
            self._chips[key] = chip
            chips.append(chip)
        self._chip_row = ft.Row(spacing=Space.XS, wrap=True, controls=chips)
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self.content = ft.Column(spacing=Space.SM, controls=[
            SectionHeader("Opponents", accent=accent, action=ft.IconButton(icon=ft.Icons.HELP_OUTLINE, icon_size=IconSize.SM, tooltip="\n".join(f"{dict(SWEEP_CLASSES)[k]}: {v}" for k, v in CLASS_HELP.items()))),
            self._presets, self._sort, self._search, self._chip_row,
            ft.Row(spacing=Space.SM, controls=[self._spinner, self._status]),
            self._list,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def set_scrolling(self, scrolling: bool) -> None:
        """In the wide layout the list scrolls under the fixed controls; stacked, it grows."""
        self._list.scroll = ft.ScrollMode.AUTO if scrolling else None
        self._list.expand = scrolling
        self._list.tight = not scrolling
        self.content.tight = not scrolling

    def _sort_options(self) -> list[ft.DropdownOption]:
        latest = self.store.latest_regulation()
        regs = self.store.available_regulations()
        opts = [
            ft.DropdownOption(key="usage:latest", text=f"Usage (Latest: {latest})"),
        ]
        for r in regs:
            if r != latest:
                opts.append(ft.DropdownOption(key=f"usage:{r}", text=f"Usage ({r})"))
        opts.extend([
            ft.DropdownOption(key="name", text="Name (A–Z)"),
            ft.DropdownOption(key="speed", text="Speed (Fastest)"),
            ft.DropdownOption(key="threat", text="Threat Level"),
        ])
        return opts

    def _current_sort_value(self) -> str:
        if self.store.sweep_sort == "usage":
            return f"usage:{self.store.sweep_regulation}" if self.store.sweep_regulation != "latest" else "usage:latest"
        return self.store.sweep_sort

    def _on_sort_changed(self, value: str | None) -> None:
        if not value:
            return
        self._limit = _INITIAL_LIMIT
        if value.startswith("usage:"):
            reg = value.split(":", 1)[1]
            self.store.set_sweep_sort("usage", reg)
        else:
            self.store.set_sweep_sort(value)

    def _query_typed(self, query: str) -> None:
        """Filter once typing pauses: each render rebuilds up to a page of cards."""
        if not is_mounted(self):
            self._set_query(query)
            return
        if self._query_later is None:
            self._query_later = Debouncer(self.page, 150, self._set_query)
        self._query_later(query)

    def _set_query(self, query: str) -> None:
        self.query = query
        self._limit = _INITIAL_LIMIT
        self.render()

    def _set_class(self, key: str | None) -> None:
        self.klass = key
        self._limit = _INITIAL_LIMIT
        for k, chip in self._chips.items():
            chip.selected = k == key
        self.render()

    def set_busy(self, busy: bool) -> None:
        self._spinner.visible = busy
        if busy:
            self._status.value = "Computing every opponent…"
        self._safe_update(self)

    def render(self) -> None:
        entries = self.store.sweep
        self._presets.value = self.store.sweep_presets
        cur_val = self._current_sort_value()
        if self._sort.value != cur_val:
            self._sort.value = cur_val
        counts = {k: 0 for k, _l in SWEEP_CLASSES}
        for e in entries:
            counts[e.klass] += 1
        for key, chip in self._chips.items():
            label = "All" if key is None else dict(SWEEP_CLASSES)[key]
            n = len(entries) if key is None else counts[key]
            chip.label = ft.Text(f"{label} {n}" if entries else label)
        q = self.query.strip().lower()
        shown = [e for e in entries if (self.klass is None or e.klass == self.klass) and (not q or q in e.name.lower())]
        attacker = self.store.species("left")
        if not entries:
            self._status.value = "Pick an attacker with at least one move." if attacker is None or not any(self.store.state.left.moves) else "Not computed yet."
            self._list.controls = []
        else:
            self._status.value = f"{len(shown)} of {len(entries)} opponents vs {attacker.name if attacker else '?'}"
            self._list.controls = [SweepCard(e, on_pick=self._on_pick) for e in shown[:self._limit]]
            if len(shown) > self._limit:
                remaining = len(shown) - self._limit

                def _show_more(_e: ft.ControlEvent) -> None:
                    self._limit += _PAGE_SIZE
                    self.render()

                self._list.controls.append(
                    ft.Container(
                        alignment=ft.Alignment.CENTER,
                        padding=ft.Padding.symmetric(vertical=Space.XS),
                        content=ft.TextButton(
                            f"Show more opponents ({remaining} remaining)…",
                            icon=ft.Icons.EXPAND_MORE,
                            on_click=_show_more,
                        ),
                    )
                )
        self._safe_update(self)

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass
