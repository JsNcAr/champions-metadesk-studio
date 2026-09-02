"""Right rail: every Champions species classified against the attacker (Threat, Wall, Neutral,
Mitigated, Crushed), searchable, with tournament sets for their moves."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite, StatusChip
from ...components.inputs import SEARCH_FIELD_STYLE
from ...components.section import SectionHeader
from ...theme import IconSize, Palette, Radius, Space
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
_LIMIT = 80


class SweepCard(ft.Container):
    def __init__(self, entry: SweepEntry, *, on_pick: Callable[[SweepEntry], None]) -> None:
        super().__init__()
        e = entry
        yours = f"{e.your_best.name} {e.your_best.min_pct:g}–{e.your_best.max_pct:g}%" if e.your_best else "no damage"
        theirs = f"{e.their_best.name} {e.their_best.min_pct:g}–{e.their_best.max_pct:g}%" if e.their_best else ("no damaging set" if e.preset else "moves unknown")
        speed = ft.Text(f"Spe {e.speed} {'▼' if e.faster else '▲'}", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.SUCCESS if e.faster else Palette.ERROR,
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
        self.bgcolor = Palette.SURFACE_2
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.ink = True
        self.tooltip = "Load as defender"
        self.on_click = lambda _e: on_pick(entry)


class SweepPanel(ft.Container):
    def __init__(self, *, store: CalcStore, accent: str, on_pick: Callable[[SweepEntry], None]) -> None:
        super().__init__()
        self.store = store
        self._on_pick = on_pick
        self.query = ""
        self.klass: str | None = None
        self._presets = ft.Switch(label="Tournament sets", value=store.sweep_presets, tooltip="Give each opponent its four most used moves from the stored rosters",
                                  on_change=lambda e: store.set_sweep_presets(bool(e.control.value)))
        self._search = ft.TextField(hint_text="Search opponent…", dense=True, prefix_icon=ft.Icons.SEARCH, **SEARCH_FIELD_STYLE, on_change=lambda e: self._set_query(e.control.value or ""))
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
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            SectionHeader("Opponents", accent=accent, action=ft.IconButton(icon=ft.Icons.HELP_OUTLINE, icon_size=IconSize.SM, tooltip="\n".join(f"{dict(SWEEP_CLASSES)[k]}: {v}" for k, v in CLASS_HELP.items()))),
            self._presets, self._search, self._chip_row,
            ft.Row(spacing=Space.SM, controls=[self._spinner, self._status]),
            self._list,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD

    def _set_query(self, query: str) -> None:
        self.query = query
        self.render()

    def _set_class(self, key: str | None) -> None:
        self.klass = key
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
            self._list.controls = [SweepCard(e, on_pick=self._on_pick) for e in shown[:_LIMIT]]
            if len(shown) > _LIMIT:
                self._list.controls.append(ft.Text(f"… {len(shown) - _LIMIT} more — narrow the search", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        self._safe_update(self)

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            if control.page is not None:
                control.update()
        except RuntimeError:
            pass
