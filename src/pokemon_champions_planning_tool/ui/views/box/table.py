"""Box table view: sortable stat columns for stat-driven work (FR-4/5/6)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import flet as ft

from ....domain.entities.box_entry import BoxEntry
from ...components import Sprite
from ...components.pokemon import TypeChip
from ...theme import Palette, Space
from .filters import SortKey

# (column label, sort key, numeric)
_COLUMNS: list[tuple[str, SortKey | None, bool]] = [
    ("", None, False),
    ("Pokémon", "name", False),
    ("Types", None, False),
    ("HP", "hp", True),
    ("Atk", "attack", True),
    ("Def", "defense", True),
    ("SpA", "special_attack", True),
    ("SpD", "special_defense", True),
    ("Spe", "speed", True),
    ("BST", "bst", True),
    ("Tags", None, False),
    ("★", None, False),
]


# Optional columns, chosen from the View menu: key -> (label, sort key, numeric)
EXTRA_COLUMNS: dict[str, tuple[str, SortKey | None, bool]] = {
    "usage": ("Usage", "usage", True),
    "abilities": ("Abilities", None, False),
    "dex": ("Dex #", None, True),
    "added": ("Added", "added", False),
    "notes": ("Notes", None, False),
}


class BoxTable(ft.Container):
    def __init__(
        self,
        *,
        on_sort: Callable[[SortKey, bool], None],
        on_select: Callable[[UUID], None],
        on_check: Callable[[UUID, bool], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_sort = on_sort
        self._on_select = on_select
        self._on_check = on_check
        self.extra: list[str] = []
        self._sort_keys: list[SortKey | None] = []
        self._usage_map: dict[str, int] = {}
        # Built rows by entry id, with the state they were built from. Selecting a row or
        # ticking a checkbox used to rebuild all ~2 500 cells of a full box; now only the
        # rows whose rendered state actually changed are built again.
        self._rows: dict[UUID, tuple[tuple, ft.DataRow]] = {}
        self.table = ft.DataTable(
            columns=[],
            rows=[],
            heading_row_height=36,
            data_row_min_height=40,
            data_row_max_height=48,
            column_spacing=Space.LG,
            divider_thickness=0,
            show_bottom_border=False,
        )
        self.content = ft.Column(controls=[self.table], scroll=ft.ScrollMode.AUTO, expand=True)
        self.expand = True
        self.set_columns([])

    def _column_defs(self) -> list[tuple[str, SortKey | None, bool]]:
        return list(_COLUMNS) + [EXTRA_COLUMNS[k] for k in self.extra if k in EXTRA_COLUMNS]

    def set_columns(self, extra: list[str]) -> None:
        """Choose the optional columns (abilities, dex, added, notes); rebuilds the header."""
        self.extra = [k for k in EXTRA_COLUMNS if k in set(extra)]
        self._rows.clear()   # the cells per row changed
        defs = self._column_defs()
        self._sort_keys = [key for _label, key, _numeric in defs]
        self.table.columns = [
            ft.DataColumn(
                label=ft.Text(label),
                numeric=numeric,
                on_sort=(lambda e, key=key: self._on_sort(key, bool(e.ascending))) if key else None,
            )
            for label, key, numeric in defs
        ]

    def update_from(
        self,
        entries: list[BoxEntry],
        *,
        sort: SortKey,
        descending: bool,
        selected_id: UUID | None,
        checked: set[UUID] | None = None,
        usage_map: dict[str, int] | None = None,
    ) -> None:
        self._usage_map = usage_map or {}
        checked = checked or set()
        if sort in self._sort_keys:
            self.table.sort_column_index = self._sort_keys.index(sort)
            self.table.sort_ascending = not descending
        rows: list[ft.DataRow] = []
        for index, entry in enumerate(entries):
            selected = entry.box_entry_id == selected_id
            checked_here = entry.box_entry_id in checked
            key = self._row_key(entry, index, selected, checked_here)
            cached = self._rows.get(entry.box_entry_id)
            if cached is not None and cached[0] == key:
                rows.append(cached[1])
                continue
            row = self._build_row(entry, index, selected, checked_here)
            self._rows[entry.box_entry_id] = (key, row)
            rows.append(row)
        self.table.rows = rows
        for stale in self._rows.keys() - {e.box_entry_id for e in entries}:
            self._rows.pop(stale, None)

    def _row_key(self, entry: BoxEntry, index: int, selected: bool, checked: bool) -> tuple:
        """Everything ``_build_row`` reads, so a row is rebuilt only when it would differ."""
        p = entry.pokemon
        return (
            index % 2, selected, checked, p.sprite_url, p.display_name, p.form_name,
            tuple(p.types), p.stats, p.total, tuple(entry.tags), entry.is_favorite,
            p.dex_number, entry.created_at, entry.notes,
            tuple(a.name for a in p.abilities),
            self._usage_count(entry) if "usage" in self.extra else None,
        )

    def _build_row(self, entry: BoxEntry, index: int, selected: bool, checked: bool) -> ft.DataRow:
        p = entry.pokemon
        return ft.DataRow(
                selected=selected,
                color=Palette.SURFACE_1 if index % 2 == 0 else None,
                on_select_change=lambda _e, eid=entry.box_entry_id: self._on_select(eid),
                cells=[
                    ft.DataCell(
                        ft.Checkbox(
                            value=checked,
                            width=32,
                            height=32,
                            on_change=(lambda e, eid=entry.box_entry_id: self._on_check(eid, bool(e.control.value))) if self._on_check else None,
                        )
                    ),
                    ft.DataCell(
                        ft.Row(
                            spacing=Space.SM,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                Sprite(p.sprite_url, size=28),
                                ft.Column(
                                    spacing=0,
                                    tight=True,
                                    controls=[
                                        ft.Text(p.display_name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE),
                                        *([ft.Text(p.form_name, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)] if p.form_name and p.form_name.lower() != "base" else []),
                                    ],
                                ),
                            ],
                        )
                    ),
                    ft.DataCell(ft.Row(spacing=Space.XS, tight=True, controls=[TypeChip(t, size="sm") for t in p.types])),
                    *[ft.DataCell(ft.Text(str(getattr(p.stats, stat)), text_align=ft.TextAlign.RIGHT)) for stat in ("hp", "attack", "defense", "special_attack", "special_defense", "speed")],
                    ft.DataCell(ft.Text(str(p.total), weight=ft.FontWeight.W_600, text_align=ft.TextAlign.RIGHT)),
                    ft.DataCell(ft.Text(", ".join(entry.tags), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
                    ft.DataCell(ft.Icon(ft.Icons.STAR if entry.is_favorite else ft.Icons.STAR_BORDER, size=16, color=Palette.PRIMARY if entry.is_favorite else Palette.DISABLED)),
                    *self._extra_cells(entry),
                ],
            )

    def _usage_count(self, entry: BoxEntry) -> int:
        p = entry.pokemon
        cid = (p.canonical_id or "").lower()
        base_cid = (getattr(p, "base_canonical_id", "") or "").lower()
        sp_name = (p.species_name or "").lower()
        return (
            self._usage_map.get(cid)
            or (self._usage_map.get(base_cid) if base_cid else None)
            or self._usage_map.get(sp_name)
            or 0
        )

    def _extra_cells(self, entry: BoxEntry) -> list[ft.DataCell]:
        p = entry.pokemon
        cells: list[ft.DataCell] = []
        for key in self.extra:
            if key == "usage":
                count = self._usage_count(entry)
                cells.append(ft.DataCell(ft.Text(f"{count:,}" if count else "0", text_align=ft.TextAlign.RIGHT)))
            elif key == "abilities":
                names = [a.name.replace("-", " ").title() for a in p.abilities]
                cells.append(ft.DataCell(ft.Text(", ".join(names), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)))
            elif key == "dex":
                cells.append(ft.DataCell(ft.Text(f"#{p.dex_number:03d}" if p.dex_number else "—", text_align=ft.TextAlign.RIGHT)))
            elif key == "added":
                cells.append(ft.DataCell(ft.Text(entry.created_at.strftime("%d %b %Y") if entry.created_at else "—", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)))
            elif key == "notes":
                cells.append(ft.DataCell(ft.Text(entry.notes or "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, tooltip=entry.notes or None)))
        return cells
