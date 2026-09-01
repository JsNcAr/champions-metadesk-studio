"""Box toolbar: one 44px row of filter/sort/view controls, an animated type drawer, and
the active-filter chip row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import flet as ft

from ...components import ActiveFilterChip
from ...tasks import Debouncer
from ...theme import TYPE_ORDER, Layout, Motion, Palette, Radius, Space, alpha, on_type_color, type_color
from .filters import SORT_LABELS, BoxFilters

_FILTER_DEBOUNCE_MS = 150
ViewMode = str  # "grid" | "table"


class _FilterChip(ft.Chip):
    def __init__(self, label: str, *, icon: str | None = None, on_toggle: Callable[[bool], None]) -> None:
        super().__init__(
            label=ft.Text(label),
            leading=ft.Icon(icon, size=16) if icon else None,
            selected=False,
            show_checkmark=False,
            on_select=lambda e: on_toggle(bool(e.control.selected)),
        )


class BoxToolbar(ft.Column):
    def __init__(
        self,
        page: ft.Page,
        *,
        on_filters: Callable[[BoxFilters], None],
        on_view_mode: Callable[[ViewMode], None],
        on_show_stats: Callable[[bool], None],
    ) -> None:
        super().__init__(spacing=Space.SM, tight=True)
        self._filters = BoxFilters()
        self._on_filters = on_filters
        self._on_view_mode = on_view_mode
        self._on_show_stats = on_show_stats
        self.show_stats = False

        self.search = ft.TextField(
            hint_text="Filter box…",
            prefix_icon=ft.Icons.FILTER_LIST,
            width=300,
            dense=True,
            height=Layout.TOOLBAR_HEIGHT - 8,
            on_change=lambda e: self._debounce(e.control.value or ""),
            on_submit=lambda e: self._set(text=e.control.value or ""),
        )
        self._debounce = Debouncer(page, _FILTER_DEBOUNCE_MS, lambda text: self._set(text=text))

        self._type_chip = ft.Chip(
            label=ft.Text("Type"),
            leading=ft.Icon(ft.Icons.CATEGORY_OUTLINED, size=16),
            selected=False,
            show_checkmark=False,
            on_select=lambda e: self._toggle_type_drawer(bool(e.control.selected)),
        )
        self._fav_chip = _FilterChip("Favourites", icon=ft.Icons.STAR_OUTLINE, on_toggle=lambda v: self._set(favourites_only=v))
        self._mega_chip = _FilterChip("Mega-capable", icon=ft.Icons.BOLT, on_toggle=lambda v: self._set(mega_capable_only=v))
        self._planned_chip = _FilterChip("Show planned", icon=ft.Icons.EDIT_NOTE, on_toggle=lambda v: self._set(show_planned=v))
        self._tags_menu = ft.PopupMenuButton(
            content=ft.Chip(label=ft.Text("Tags"), leading=ft.Icon(ft.Icons.TAG, size=16), show_checkmark=False),
            items=[],
            tooltip="Filter by tag",
        )

        self._sort = ft.Dropdown(
            value="name",
            options=[ft.DropdownOption(key=k, text=label) for k, label in SORT_LABELS.items()],
            width=150,
            dense=True,
            leading_icon=ft.Icons.SORT,
            on_select=lambda e: self._set(sort=e.control.value or "name"),
        )
        self._direction = ft.IconButton(
            icon=ft.Icons.ARROW_UPWARD,
            icon_size=20,
            tooltip="Ascending — click for descending",
            on_click=lambda _e: self._set(descending=not self._filters.descending),
        )
        self._view_mode = ft.SegmentedButton(
            selected=["grid"],
            allow_multiple_selection=False,
            allow_empty_selection=False,
            show_selected_icon=False,
            segments=[
                ft.Segment(value="grid", icon=ft.Icon(ft.Icons.GRID_VIEW), tooltip="Cards"),
                ft.Segment(value="table", icon=ft.Icon(ft.Icons.TABLE_ROWS), tooltip="Table"),
            ],
            on_change=lambda e: self._on_view_mode(next(iter(e.control.selected or ["grid"]))),
        )
        self._stats_item = ft.PopupMenuItem(content=ft.Text("Show stats on cards"), checked=False, on_click=lambda _e: self._toggle_stats())
        self._view_menu = ft.PopupMenuButton(icon=ft.Icons.TUNE, tooltip="View options", items=[self._stats_item])

        self.row = ft.Row(
            spacing=Space.SM,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
            controls=[
                self.search,
                self._type_chip,
                self._fav_chip,
                self._mega_chip,
                self._planned_chip,
                self._tags_menu,
                ft.Container(expand=True),
                self._sort,
                self._direction,
                self._view_mode,
                self._view_menu,
            ],
        )

        self._type_chips: dict[str, ft.Chip] = {}
        for t in TYPE_ORDER:
            chip = ft.Chip(
                label=ft.Text(t.capitalize()),
                selected=False,
                show_checkmark=False,
                selected_color=type_color(t),
                bgcolor=alpha(type_color(t), 0.15),
                label_text_style=ft.TextStyle(color=Palette.ON_SURFACE),
                on_select=lambda e, t=t: self._toggle_type(t, bool(e.control.selected)),
            )
            self._type_chips[t] = chip
        self.type_drawer = ft.Container(
            content=ft.Row(spacing=Space.SM, run_spacing=Space.SM, wrap=True, controls=list(self._type_chips.values())),
            bgcolor=Palette.SURFACE_1,
            border_radius=Radius.MD,
            padding=Space.MD,
            visible=False,
            animate=ft.Animation(Motion.NORMAL_MS, Motion.CURVE),
        )
        self.active_row = ft.Row(spacing=Space.SM, wrap=True, visible=False)
        self.controls = [self.row, self.type_drawer, self.active_row]

    # -- state ---------------------------------------------------------------------------

    @property
    def filters(self) -> BoxFilters:
        return self._filters

    def set_available_tags(self, tags: list[str]) -> None:
        self._tags_menu.items = [
            ft.PopupMenuItem(
                content=ft.Text(tag),
                checked=tag.lower() in self._filters.tags,
                on_click=lambda _e, tag=tag: self._toggle_tag(tag),
            )
            for tag in tags
        ] or [ft.PopupMenuItem(content=ft.Text("No tags yet"), disabled=True)]

    def _set(self, **changes) -> None:
        new = replace(self._filters, **changes)
        if new == self._filters:
            return
        self._filters = new
        self._sync_controls()
        self._on_filters(new)

    def _toggle_type(self, type_name: str, selected: bool) -> None:
        types = set(self._filters.types)
        (types.add if selected else types.discard)(type_name)
        self._set(types=frozenset(types))

    def _toggle_tag(self, tag: str) -> None:
        tags = set(self._filters.tags)
        key = tag.lower()
        (tags.discard if key in tags else tags.add)(key)
        self._set(tags=frozenset(tags))

    def _toggle_type_drawer(self, open_: bool) -> None:
        self.type_drawer.visible = open_
        self._safe_update(self.type_drawer)
        self._safe_update(self._type_chip)

    def _toggle_stats(self) -> None:
        self.show_stats = not self.show_stats
        self._stats_item.checked = self.show_stats
        self._on_show_stats(self.show_stats)

    def remove(self, field_key: str) -> None:
        self._filters = self._filters.without(field_key)
        self._sync_controls()
        self._on_filters(self._filters)

    def clear(self) -> None:
        self._filters = self._filters.cleared()
        self._sync_controls()
        self._on_filters(self._filters)

    def _sync_controls(self) -> None:
        f = self._filters
        self.search.value = f.text
        self._fav_chip.selected = f.favourites_only
        self._mega_chip.selected = f.mega_capable_only
        self._planned_chip.selected = f.show_planned
        for t, chip in self._type_chips.items():
            chip.selected = t in f.types
        self._type_chip.label = ft.Text(f"Type · {len(f.types)}" if f.types else "Type")
        self._sort.value = f.sort
        self._direction.icon = ft.Icons.ARROW_DOWNWARD if f.descending else ft.Icons.ARROW_UPWARD
        self._direction.tooltip = "Descending — click for ascending" if f.descending else "Ascending — click for descending"
        chips: list[ft.Control] = [ActiveFilterChip(label, on_remove=lambda k=key: self.remove(k)) for key, label in f.active_labels()]
        if chips:
            chips.append(ft.TextButton("Clear all", on_click=lambda _e: self.clear()))
        self.active_row.controls = chips
        self.active_row.visible = bool(chips)
        self._safe_update(self)

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        from ...tasks import is_mounted

        if is_mounted(control):
            control.update()


__all__ = ["BoxToolbar", "on_type_color"]
