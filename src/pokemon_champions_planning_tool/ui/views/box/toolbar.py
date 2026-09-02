"""Box toolbar: one 44px row of filter/sort/view controls, an animated type drawer, and
the active-filter chip row."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import flet as ft

from ...components import ActiveFilterChip
from ...components.inputs import SEARCH_FIELD_STYLE
from ...tasks import Debouncer
from ...theme import TYPE_ORDER, Layout, Motion, Palette, Radius, Space, alpha, on_type_color, type_color
from ...theme import STAT_COLORS, STAT_LABELS, STAT_ORDER
from .filters import BST_MAX, BST_MIN, SORT_LABELS, STAT_MAX, STAT_MIN, BoxFilters
from .table import EXTRA_COLUMNS

_FILTER_DEBOUNCE_MS = 150
ViewMode = str  # "grid" | "table"


class _FilterChip(ft.Chip):
    def __init__(self, label: str, *, icon: str | None = None, icon_color: str | None = None, on_toggle: Callable[[bool], None]) -> None:
        super().__init__(
            label=ft.Text(label),
            leading=ft.Icon(icon, size=16, color=icon_color) if icon else None,
            selected=False,
            show_checkmark=False,
            on_select=lambda e: on_toggle(bool(e.control.selected)),
        )


def _menu_chip(icon: str, label: ft.Text) -> ft.Container:
    """Chip-shaped trigger for a PopupMenuButton.

    A real ``ft.Chip`` with no handler paints as disabled inside a menu button, so the
    trigger is a Container styled to the same 32px pill, with a caret to signal a menu.
    """
    return ft.Container(
        content=ft.Row(
            spacing=Space.XS,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[ft.Icon(icon, size=16, color=Palette.ON_SURFACE_VARIANT), label, ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=Palette.ON_SURFACE_VARIANT)],
        ),
        # No ``alignment`` or ``height``: a Container with alignment fills the width a Wrap
        # offers it. Vertical padding brings the pill to the row's 32px.
        padding=ft.Padding.only(left=Space.MD, right=Space.XS, top=5, bottom=5),
        border_radius=Radius.SM,
        border=ft.Border.all(1, Palette.OUTLINE),
    )


class BoxToolbar(ft.Column):
    def __init__(
        self,
        page: ft.Page,
        *,
        on_filters: Callable[[BoxFilters], None],
        on_view_mode: Callable[[ViewMode], None],
        on_show_stats: Callable[[bool], None],
        on_columns: Callable[[list[str]], None] | None = None,
    ) -> None:
        super().__init__(spacing=Space.SM, tight=True)
        self._filters = BoxFilters()
        self._on_filters = on_filters
        self._on_view_mode = on_view_mode
        self._on_show_stats = on_show_stats
        self.show_stats = False

        self.search = ft.TextField(**SEARCH_FIELD_STYLE, 
            hint_text="Filter box…",
            prefix_icon=ft.Icons.FILTER_LIST,
            width=260,
            dense=True,
            height=Layout.TOOLBAR_HEIGHT - 8,
            on_change=lambda e: self._debounce(e.control.value or ""),
            on_submit=lambda e: self._set(text=e.control.value or ""),
        )
        self._debounce = Debouncer(page, _FILTER_DEBOUNCE_MS, lambda text: self._set(text=text))

        self._type_chip = ft.Chip(
            label=ft.Text("Type"),
            leading=ft.Icon(ft.Icons.CATEGORY_OUTLINED, size=16, color=Palette.SECONDARY),
            selected=False,
            show_checkmark=False,
            on_select=lambda e: self._toggle_drawer("types", bool(e.control.selected)),
        )
        self._bst_chip = ft.Chip(
            label=ft.Text("BST"),
            leading=ft.Icon(ft.Icons.FUNCTIONS, size=16, color=Palette.TERTIARY),
            selected=False,
            show_checkmark=False,
            on_select=lambda e: self._toggle_drawer("bst", bool(e.control.selected)),
        )
        self._stats_chip = ft.Chip(
            label=ft.Text("Stats"),
            leading=ft.Icon(ft.Icons.BAR_CHART, size=16, color=Palette.WARNING),
            selected=False,
            show_checkmark=False,
            on_select=lambda e: self._toggle_drawer("stats", bool(e.control.selected)),
        )
        self._fav_chip = _FilterChip("Favourites", icon=ft.Icons.STAR_OUTLINE, icon_color=Palette.PRIMARY, on_toggle=lambda v: self._set(favourites_only=v))
        self._mega_chip = _FilterChip("Mega-capable", icon=ft.Icons.BOLT, icon_color=Palette.PRIMARY, on_toggle=lambda v: self._set(mega_capable_only=v))
        self._tags_label = ft.Text("Tags", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE)
        self._tags_menu = ft.PopupMenuButton(content=_menu_chip(ft.Icons.TAG, self._tags_label), items=[], tooltip="Filter by tag")

        self._sort_label = ft.Text(SORT_LABELS["name"], theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE)
        self._sort_items = {
            key: ft.PopupMenuItem(content=ft.Text(label), checked=(key == "name"), on_click=lambda _e, key=key: self._set(sort=key))
            for key, label in SORT_LABELS.items()
        }
        self._sort = ft.PopupMenuButton(content=_menu_chip(ft.Icons.SORT, self._sort_label), items=list(self._sort_items.values()), tooltip="Sort by")
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
        self._planned_item = ft.PopupMenuItem(content=ft.Text("Show planned Pokémon"), checked=False, on_click=lambda _e: self._set(show_planned=not self._filters.show_planned))
        self._on_columns = on_columns
        self.columns: list[str] = []
        self._column_items: dict[str, ft.PopupMenuItem] = {
            key: ft.PopupMenuItem(content=ft.Text(f"Column: {label}"), checked=False, on_click=lambda _e, key=key: self._toggle_column(key))
            for key, (label, _sort, _numeric) in EXTRA_COLUMNS.items()
        }
        self._view_menu = ft.PopupMenuButton(
            icon=ft.Icons.TUNE, tooltip="View options",
            items=[self._stats_item, self._planned_item, ft.PopupMenuItem(), *self._column_items.values()],
        )

        # Two groups: the filter chips wrap when the panel narrows; sort/view stay pinned right.
        # A wrapping Row must never hold an ``expand`` child — Flutter's Wrap rejects Expanded
        # and renders the whole view as an error box (see tests/_ui_stubs.check_layout).
        self.filter_group = ft.Row(
            spacing=Space.SM,
            run_spacing=Space.SM,
            wrap=True,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                self.search,
                self._type_chip,
                self._bst_chip,
                self._stats_chip,
                self._fav_chip,
                self._mega_chip,
                self._tags_menu,
            ],
        )
        self.view_group = ft.Row(
            spacing=Space.SM,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[self._sort, self._direction, self._view_mode, self._view_menu],
        )
        self.row = ft.Row(
            spacing=Space.LG,
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[self.filter_group, self.view_group],
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
        self._types_section = ft.Column(
            spacing=Space.SM, tight=True, visible=False,
            controls=[
                ft.Text("TYPES", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT),
                ft.Row(spacing=Space.SM, run_spacing=Space.SM, wrap=True, controls=list(self._type_chips.values())),
            ],
        )
        self._bst_label = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._bst_slider = ft.RangeSlider(
            min=BST_MIN, max=BST_MAX, start_value=BST_MIN, end_value=BST_MAX, divisions=(BST_MAX - BST_MIN) // 10,
            label="{value}", expand=True,
            on_change=lambda e: self._preview_bst(e.control),
            on_change_end=lambda e: self._set(bst_range=(int(e.control.start_value), int(e.control.end_value))),
        )
        self._bst_section = ft.Column(
            spacing=Space.XS, tight=True, visible=False,
            controls=[
                ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                    ft.Text("BASE STAT TOTAL", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT), self._bst_label]),
                self._bst_slider,
            ],
        )
        self._stat_sliders: dict[str, ft.RangeSlider] = {}
        self._stat_labels: dict[str, ft.Text] = {}
        stat_rows: list[ft.Control] = [ft.Text("STAT RANGES", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)]
        for stat in STAT_ORDER:
            slider = ft.RangeSlider(
                min=STAT_MIN, max=STAT_MAX, start_value=STAT_MIN, end_value=STAT_MAX, divisions=51, label="{value}", expand=True,
                active_color=STAT_COLORS[stat],
                on_change=lambda e, stat=stat: self._preview_stat(stat, e.control),
                on_change_end=lambda e, stat=stat: self._set_stat_range(stat, int(e.control.start_value), int(e.control.end_value)),
            )
            label = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, width=72, text_align=ft.TextAlign.RIGHT)
            self._stat_sliders[stat] = slider
            self._stat_labels[stat] = label
            stat_rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text(STAT_LABELS[stat], theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=STAT_COLORS[stat], width=32), slider, label]))
        self._stats_section = ft.Column(spacing=Space.XS, tight=True, visible=False, controls=stat_rows)

        self.drawer = ft.Container(
            content=ft.Column(spacing=Space.MD, tight=True, controls=[self._types_section, self._bst_section, self._stats_section]),
            bgcolor=Palette.SURFACE_1,
            border_radius=Radius.MD,
            padding=Space.MD,
            visible=False,
            animate=ft.Animation(Motion.NORMAL_MS, Motion.CURVE),
        )
        self.type_drawer = self.drawer  # backwards-compatible name
        self._sections = {"types": (self._type_chip, self._types_section), "bst": (self._bst_chip, self._bst_section), "stats": (self._stats_chip, self._stats_section)}
        self.active_row = ft.Row(spacing=Space.SM, wrap=True, visible=False)
        self.controls = [self.row, self.drawer, self.active_row]
        self._sync_range_labels()

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

    def _toggle_drawer(self, section: str, open_: bool) -> None:
        chip, panel = self._sections[section]
        panel.visible = open_
        chip.selected = open_
        self.drawer.visible = any(p.visible for _c, p in self._sections.values())
        self._safe_update(self)

    def _preview_bst(self, slider: ft.RangeSlider) -> None:
        self._bst_label.value = f"{int(slider.start_value)} – {int(slider.end_value)}"
        self._safe_update(self._bst_label)

    def _preview_stat(self, stat: str, slider: ft.RangeSlider) -> None:
        self._stat_labels[stat].value = f"{int(slider.start_value)} – {int(slider.end_value)}"
        self._safe_update(self._stat_labels[stat])

    def _set_stat_range(self, stat: str, lo: int, hi: int) -> None:
        ranges = dict(self._filters.stat_ranges)
        if (lo, hi) == (STAT_MIN, STAT_MAX):
            ranges.pop(stat, None)
        else:
            ranges[stat] = (lo, hi)
        self._set(stat_ranges=ranges)

    def _sync_range_labels(self) -> None:
        f = self._filters
        self._bst_slider.start_value, self._bst_slider.end_value = f.bst_range
        self._bst_label.value = f"{f.bst_range[0]} – {f.bst_range[1]}"
        for stat, slider in self._stat_sliders.items():
            lo, hi = f.stat_ranges.get(stat, (STAT_MIN, STAT_MAX))
            slider.start_value, slider.end_value = lo, hi
            self._stat_labels[stat].value = f"{lo} – {hi}"

    def set_view_state(self, view_mode: str, show_stats: bool) -> None:
        """Reflect restored preferences in the grid/table switch and the View menu."""
        self._view_mode.selected = [view_mode]
        self.show_stats = show_stats
        self._stats_item.checked = show_stats

    def set_columns(self, columns: list[str]) -> None:
        self.columns = [k for k in EXTRA_COLUMNS if k in set(columns)]
        for key, item in self._column_items.items():
            item.checked = key in self.columns

    def _toggle_column(self, key: str) -> None:
        current = set(self.columns)
        (current.discard if key in current else current.add)(key)
        self.set_columns(list(current))
        if self._on_columns is not None:
            self._on_columns(self.columns)

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
        self._planned_item.checked = f.show_planned
        for t, chip in self._type_chips.items():
            chip.selected = t in f.types
        self._type_chip.label = ft.Text(f"Type · {len(f.types)}" if f.types else "Type")
        self._bst_chip.label = ft.Text(f"BST {f.bst_range[0]}–{f.bst_range[1]}" if f.bst_range != (BST_MIN, BST_MAX) else "BST")
        active_stats = [k for k, v in f.stat_ranges.items() if v != (STAT_MIN, STAT_MAX)]
        self._stats_chip.label = ft.Text(f"Stats · {len(active_stats)}" if active_stats else "Stats")
        self._sync_range_labels()
        self._sort_label.value = SORT_LABELS.get(f.sort, f.sort)
        self._tags_label.value = f"Tags · {len(f.tags)}" if f.tags else "Tags"
        for key, item in self._sort_items.items():
            item.checked = key == f.sort
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
