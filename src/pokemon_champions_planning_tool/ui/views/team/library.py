"""Team library: every team as a tile (name, format, six sprites, last edit), searchable.

Opened from the team switcher, Ctrl+L or the team menu; with no teams it is the Teams view's
empty state. A tile opens its team in the editor; its menu renames, duplicates, compares,
copies or deletes it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import flet as ft

from ...components import EmptyState, Sprite, StatusChip
from ...components.inputs import SEARCH_FIELD_STYLE
from ...format import relative_time
from ...tasks import is_mounted
from ...theme import IconSize, Palette, Radius, Space
from .store import LibraryRow

SORTS: tuple[tuple[str, str], ...] = (("recent", "Recently edited"), ("name", "Name"), ("complete", "Most complete"))
TILE_HEIGHT = 150
TILE_COL = {"xs": 12, "md": 6, "xl": 4}


@dataclass
class LibraryCallbacks:
    on_open: Callable[[UUID], None]
    on_new: Callable[[], None]
    on_import: Callable[[], None]
    on_rename: Callable[[UUID], None]
    on_duplicate: Callable[[UUID], None]
    on_compare: Callable[[UUID], None]
    on_copy: Callable[[UUID], None]
    on_delete: Callable[[UUID], None]
    on_back: Callable[[], None]
    format_label: Callable[[str | None], str]


def sort_rows(rows: list[LibraryRow], sort: str) -> list[LibraryRow]:
    by_name = sorted(rows, key=lambda r: r.name.lower())
    if sort == "name":
        return by_name
    if sort == "complete":
        return sorted(by_name, key=lambda r: r.filled, reverse=True)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(by_name, key=lambda r: _aware(r.updated_at) or epoch, reverse=True)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class TeamTile(ft.Container):
    def __init__(self, row: LibraryRow, *, active: bool, cb: LibraryCallbacks) -> None:
        super().__init__()
        self.row = row
        tid = row.team_id
        sprites: list[ft.Control] = []
        by_slot = {m.slot: m for m in row.members}
        for slot in range(1, 7):
            member = by_slot.get(slot)
            sprites.append(Sprite(member.sprite_url, size=40, tooltip=member.name) if member is not None else
                           ft.Container(width=40, height=40, border_radius=Radius.PILL, border=ft.Border.all(1, Palette.OUTLINE_VARIANT)))
        menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_size=IconSize.MD, tooltip="Team actions", items=[
            ft.PopupMenuItem(content=ft.Text("Open"), icon=ft.Icons.OPEN_IN_NEW, on_click=lambda _e: cb.on_open(tid)),
            ft.PopupMenuItem(content=ft.Text("Rename…"), icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _e: cb.on_rename(tid)),
            ft.PopupMenuItem(content=ft.Text("Duplicate…"), icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: cb.on_duplicate(tid)),
            ft.PopupMenuItem(content=ft.Text("Compare with…"), icon=ft.Icons.COMPARE_ARROWS, on_click=lambda _e: cb.on_compare(tid)),
            ft.PopupMenuItem(content=ft.Text("Copy Showdown text"), icon=ft.Icons.UPLOAD, on_click=lambda _e: cb.on_copy(tid)),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(content=ft.Text("Delete…"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: cb.on_delete(tid)),
        ])
        self.content = ft.Column(spacing=Space.SM, tight=True, controls=[
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text(row.name, theme_style=ft.TextThemeStyle.TITLE_SMALL, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                *([StatusChip("Open", "primary")] if active else []),
                menu,
            ]),
            ft.Row(spacing=Space.XS, controls=sprites),
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                StatusChip(cb.format_label(row.format_id), "tertiary", icon=ft.Icons.RULE),
                ft.Text(f"{row.filled}/6", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE if row.filled == 6 else Palette.ON_SURFACE_VARIANT),
                ft.Container(expand=True),
                ft.Text(f"Edited {relative_time(row.updated_at)}" if row.updated_at else "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            ]),
        ])
        self.col = TILE_COL
        self.height = TILE_HEIGHT
        self.padding = Space.MD
        self.border_radius = Radius.MD
        self.bgcolor = Palette.SURFACE_2
        self.border = ft.Border.all(2 if active else 1, Palette.PRIMARY if active else Palette.OUTLINE_VARIANT)
        self.ink = True
        self.tooltip = f"Open {row.name}"
        self.on_click = lambda _e: cb.on_open(tid)


class TeamLibrary(ft.Column):
    def __init__(self, cb: LibraryCallbacks) -> None:
        super().__init__(spacing=Space.MD, expand=True)
        self.cb = cb
        self.rows: list[LibraryRow] = []
        self.active_id: UUID | None = None
        self.sort = "recent"
        self.loading = False
        self._search = ft.TextField(hint_text="Search teams or Pokémon…", prefix_icon=ft.Icons.SEARCH, dense=True, expand=True, **SEARCH_FIELD_STYLE,
                                    on_change=lambda _e: self.render())
        self._sort = ft.Dropdown(label="Sort", dense=True, width=200, value=self.sort, options=[ft.DropdownOption(key=k, text=t) for k, t in SORTS],
                                 on_select=lambda e: self.set_sort(e.control.value or "recent"))
        self._back = ft.TextButton("Back to team", icon=ft.Icons.ARROW_BACK, on_click=lambda _e: cb.on_back(), visible=False)
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._grid = ft.ResponsiveRow(spacing=Space.GRID_GAP, run_spacing=Space.GRID_GAP)
        self._empty = EmptyState(ft.Icons.GROUPS_OUTLINED, "No teams yet", "Create a team, or import one from a Showdown paste or the Meta explorer.",
                                 action_label="Create team", on_action=cb.on_new, secondary_label="Import", on_secondary=cb.on_import)
        self._empty.visible = False
        self.controls = [
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self._back, self._search, self._sort,
                ft.FilledTonalButton("New team", icon=ft.Icons.ADD, on_click=lambda _e: cb.on_new()),
                ft.OutlinedButton("Import", icon=ft.Icons.DOWNLOAD, on_click=lambda _e: cb.on_import()),
            ]),
            ft.Row(spacing=Space.SM, controls=[self._spinner, self._status]),
            ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, controls=[self._grid, ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._empty])]),
        ]

    def set_loading(self, loading: bool) -> None:
        self.loading = loading
        self._spinner.visible = loading
        if loading and not self.rows:
            self._status.value = "Loading teams…"
        self._safe_update(self)

    def set_rows(self, rows: list[LibraryRow], active_id: UUID | None) -> None:
        self.rows = list(rows)
        self.active_id = active_id
        self.loading = False
        self._spinner.visible = False
        self.render()

    def set_sort(self, sort: str) -> None:
        self.sort = sort
        self._sort.value = sort
        self.render()

    def shown(self) -> list[LibraryRow]:
        query = self._search.value or ""
        return [r for r in sort_rows(self.rows, self.sort) if r.matches(query)]

    def render(self) -> None:
        shown = self.shown()
        self._back.visible = self.active_id is not None
        self._empty.visible = not self.rows and not self.loading
        self._grid.controls = [TeamTile(r, active=r.team_id == self.active_id, cb=self.cb) for r in shown]
        if not self.rows:
            self._status.value = "" if not self.loading else "Loading teams…"
        elif len(shown) == len(self.rows):
            self._status.value = f"{len(self.rows)} team{'s' if len(self.rows) != 1 else ''}"
        else:
            self._status.value = f"{len(shown)} of {len(self.rows)} teams match"
        self._safe_update(self)

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        if is_mounted(control):
            control.update()


__all__ = ["LibraryCallbacks", "SORTS", "TeamLibrary", "TeamTile", "sort_rows"]
