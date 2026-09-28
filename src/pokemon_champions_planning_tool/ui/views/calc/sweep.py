"""The side panel's Opponents tab: every Champions species classified against the attacker
(Threat, Wall, Neutral, Mitigated, Crushed), searchable, with tournament sets for their moves.
Its controls take two lines: search with an options menu, and the classes as count pills."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite, StatusChip
from ...components.help_button import help_button
from ...components.inputs import SEARCH_FIELD_STYLE
from ...tasks import Debouncer, is_mounted, safe_update
from ...theme import Palette, Radius, Space
from .classes import CLASS_BG, CLASS_BORDER, CLASS_COLOR, CLASS_HELP, CLASS_TONES
from .damage_line import damage_line, speed_mark
from .state import SWEEP_CLASSES, SweepEntry
from .store import CalcStore

SWEEP_HELP: tuple[str, ...] = (
    "Every Champions species against your Attacker, with their most used tournament set when \"Tournament sets\" is on. "
    "Click one to load it as the Defender. The sliders menu beside the search sorts the list and switches tournament sets on or off.",
    "The coloured pills filter by class (click again for everyone); the colours, from your side:",
    *(f"{label}: {CLASS_HELP[key]}." for key, label in SWEEP_CLASSES),
    "Spe ▲ means you move first (Tailwind and Trick Room included); ▼ that they do.",
)

_INITIAL_LIMIT = 40
_PAGE_SIZE = 40


class SweepCard(ft.Container):
    def __init__(self, entry: SweepEntry, *, on_pick: Callable[[SweepEntry], None]) -> None:
        super().__init__()
        e = entry
        # Name, speed and class on one line; under it each side's best hit as a small gauge.
        self.name = ft.Text(e.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self.klass_chip = StatusChip(dict(SWEEP_CLASSES)[e.klass], CLASS_TONES[e.klass], tooltip=CLASS_HELP[e.klass])  # type: ignore[arg-type]
        self.sprite = Sprite(get_pokemon_sprite_url(e.canonical_id), size=36)
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            self.sprite,
            ft.Column(spacing=2, tight=True, expand=True, controls=[
                ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self.name, speed_mark(e.speed, e.faster), self.klass_chip]),
                damage_line("you", e.your_best, "no damage"),
                damage_line("them", e.their_best, "no damaging set" if e.preset else "moves unknown"),
            ]),
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
        # One line of controls: search, then an options menu (sort, tournament sets) and help.
        self.sort_value = self._current_sort_value()
        self._options = ft.PopupMenuButton(icon=ft.Icons.TUNE, icon_size=20, tooltip="Sort and tournament sets", items=[])
        self._search = ft.TextField(hint_text="Search…", dense=True, prefix_icon=ft.Icons.SEARCH, **SEARCH_FIELD_STYLE, expand=True,
                                    on_change=lambda e: self._query_typed(e.control.value or ""))
        self._query_later: Debouncer | None = None
        # The classes as small count pills on one line; their names are in the tooltips (and
        # on every card), the colours match the cards.
        self._chips: dict[str | None, ft.Container] = {}
        self._chip_labels: dict[str | None, ft.Text] = {}
        for key, label in ((None, "All"), *SWEEP_CLASSES):
            text = ft.Text(label if key is None else "", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE)
            controls: list[ft.Control] = [text] if key is None else [
                ft.Container(width=8, height=8, border_radius=4, bgcolor=CLASS_COLOR[key]), text]
            self._chip_labels[key] = text
            self._chips[key] = ft.Container(
                content=ft.Row(spacing=4, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls),
                padding=ft.Padding.symmetric(horizontal=6, vertical=3), border_radius=Radius.PILL, ink=True,
                tooltip="Every opponent" if key is None else f"{label}: {CLASS_HELP[key]}",
                on_click=lambda _e, key=key: self._set_class(None if key == self.klass else key),
            )
        self._chip_row = ft.Row(spacing=3, run_spacing=Space.XS, wrap=True, controls=list(self._chips.values()))
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self._spinner = ft.ProgressRing(width=14, height=14, stroke_width=2, visible=False)
        self._list = ft.Column(spacing=Space.XS, tight=True, controls=[])
        self.content = ft.Column(spacing=Space.SM, controls=[
            ft.Row(spacing=0, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self._search, self._options, help_button("Opponents", SWEEP_HELP, tooltip="What the colours mean"),
            ]),
            self._chip_row,
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._spinner, self._status]),
            self._list,
        ])
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.padding = Space.MD
        self._draw_options()
        self._draw_chips()

    def set_scrolling(self, scrolling: bool) -> None:
        """In the wide layout the list scrolls under the fixed controls; stacked, it grows."""
        self._list.scroll = ft.ScrollMode.AUTO if scrolling else None
        self._list.expand = scrolling
        self._list.tight = not scrolling
        self.content.tight = not scrolling

    def sort_options(self) -> list[tuple[str, str]]:
        """(key, label) of every sort: usage per regulation, then name, speed and threat."""
        latest = self.store.latest_regulation()
        opts = [("usage:latest", f"Usage (Latest: {latest})")]
        opts += [(f"usage:{r}", f"Usage ({r})") for r in self.store.available_regulations() if r != latest]
        return opts + [("name", "Name (A–Z)"), ("speed", "Speed (Fastest)"), ("threat", "Threat Level")]

    def _draw_options(self) -> None:
        def item(label: str, checked: bool, on_click) -> ft.PopupMenuItem:
            return ft.PopupMenuItem(content=ft.Text(label, weight=ft.FontWeight.W_700 if checked else None),
                                    icon=ft.Icons.CHECK if checked else None, on_click=lambda _e: on_click())

        items = [ft.PopupMenuItem(content=ft.Text("SORT BY", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT), disabled=True)]
        items += [item(label, key == self.sort_value, lambda key=key: self._on_sort_changed(key)) for key, label in self.sort_options()]
        items += [ft.PopupMenuItem(), item("Tournament sets: each opponent's most used moves", self.store.sweep_presets,
                                           lambda: self.store.set_sweep_presets(not self.store.sweep_presets))]
        self._options.items = items
        label = dict(self.sort_options()).get(self.sort_value, "")
        self._options.tooltip = f"Sorted by {label}" + (" · tournament sets" if self.store.sweep_presets else " · no tournament sets")

    def _draw_chips(self, counts: dict[str | None, int] | None = None) -> None:
        for key, chip in self._chips.items():
            on = key == self.klass
            n = None if counts is None else counts.get(key, 0)
            if key is None:
                self._chip_labels[key].value = "All"      # the total is in the status line below
            else:
                self._chip_labels[key].value = str(n) if n is not None else "–"
            chip.bgcolor = Palette.SURFACE_4 if on else Palette.SURFACE_3
            chip.border = ft.Border.all(1, Palette.PRIMARY if on else Palette.OUTLINE_VARIANT)
            self._chip_labels[key].weight = ft.FontWeight.W_700 if on else ft.FontWeight.W_500

    def _current_sort_value(self) -> str:
        if self.store.sweep_sort == "usage":
            return f"usage:{self.store.sweep_regulation}" if self.store.sweep_regulation != "latest" else "usage:latest"
        return self.store.sweep_sort

    def _on_sort_changed(self, value: str | None) -> None:
        if not value:
            return
        self._limit = _INITIAL_LIMIT
        self.sort_value = value
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
        """Show one class (a second click on it shows all again)."""
        self.klass = key
        self._limit = _INITIAL_LIMIT
        self.render()

    def set_busy(self, busy: bool) -> None:
        self._spinner.visible = busy
        if busy:
            self._status.value = "Computing every opponent…"
        safe_update(self)

    def render(self) -> None:
        entries = self.store.sweep
        self.sort_value = self._current_sort_value()
        self._draw_options()
        counts: dict[str | None, int] = {k: 0 for k, _l in SWEEP_CLASSES}
        for e in entries:
            counts[e.klass] += 1
        counts[None] = len(entries)
        self._draw_chips(counts if entries else None)
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
        safe_update(self)

