"""Item picker: categories, search, legality switch, species-aware Mega Stone handling."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from .....infrastructure.database.models import ItemRecord
from ....catalogs import Catalogs
from ....components import EmptyState, StatusChip
from ....components.inputs import SEARCH_FIELD_STYLE
from ....tasks import is_mounted
from ....theme import STAT_COLORS, STAT_LABELS, IconSize, Palette, Radius, Space

_MAX_ROWS = 80


def _category_label(category: str | None) -> str:
    return (category or "other").replace("-", " ").title()


class ItemPickerDialog(ft.AlertDialog):
    def __init__(
        self,
        *,
        catalogs: Catalogs,
        species_name: str,
        current_item_id: str | None,
        on_pick: Callable[[str | None], None],
        on_close: Callable[[], None],
        mega: bool = True,
    ) -> None:
        super().__init__(modal=True)
        self._catalogs = catalogs
        self._mega = mega           # False: the team's format has no Mega Evolution, so no Mega Stones
        self._species = (species_name or "").lower()
        self._on_pick = on_pick
        self._on_close = on_close
        self._legal_only = True
        self._category = "all"
        self._show_incompatible = False

        all_items = list(catalogs.items_by_id.values())
        categories = sorted({(i.category or "other") for i in all_items}, key=_category_label)

        self._search = ft.TextField(**SEARCH_FIELD_STYLE, hint_text="Search items…", prefix_icon=ft.Icons.SEARCH, autofocus=True, dense=True, expand=True,
                                    on_change=lambda _e: self._refresh(), on_submit=lambda _e: self._pick_first())
        self._legal = ft.Switch(label="Champions-legal only", value=True, on_change=lambda e: self._set_legal(bool(e.control.value)))
        self._categories = ft.ListView(width=160, spacing=2, controls=[])
        self._category_tiles: dict[str, ft.Container] = {}
        for key, label in [("all", "All items")] + [(c, _category_label(c)) for c in categories]:
            tile = ft.Container(
                content=ft.Text(label, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE),
                padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM),
                border_radius=Radius.SM,
                on_click=lambda _e, key=key: self._set_category(key),
                ink=True,
            )
            self._category_tiles[key] = tile
            self._categories.controls.append(tile)
        self._list = ft.ListView(spacing=Space.XS, expand=True)

        self.title = ft.Text("Choose held item")
        self.content = ft.Container(
            width=680,
            height=560,
            content=ft.Column(
                spacing=Space.MD,
                expand=True,
                controls=[
                    ft.Row(spacing=Space.MD, controls=[self._search, self._legal]),
                    ft.Row(spacing=Space.MD, expand=True, vertical_alignment=ft.CrossAxisAlignment.START, controls=[self._categories, ft.VerticalDivider(width=1), self._list]),
                ],
            ),
        )
        self.actions = [
            ft.TextButton("Remove item", icon=ft.Icons.CLOSE, visible=current_item_id is not None, on_click=lambda _e: self._on_pick(None)),
            ft.Container(expand=True),
            ft.TextButton("Cancel", on_click=lambda _e: self._on_close()),
        ]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._refresh()

    # -- filtering -------------------------------------------------------------------------------

    def _set_legal(self, value: bool) -> None:
        self._legal_only = value
        self._refresh()

    def _set_category(self, key: str) -> None:
        self._category = key
        self._refresh()

    def _candidates(self) -> tuple[list[ItemRecord], list[ItemRecord], list[ItemRecord]]:
        """(compatible stones, other items, incompatible stones) after search/category/legal."""
        source = list(self._catalogs.champions_items) if self._legal_only else list(self._catalogs.items_by_id.values())
        if self._category != "all":
            source = [i for i in source if (i.category or "other") == self._category]
        q = (self._search.value or "").strip().lower()
        if q:
            source = [i for i in source if q in i.display_name.lower() or q in (i.short_effect or "").lower()]
        compatible, others, incompatible = [], [], []
        for item in sorted(source, key=lambda i: i.display_name.lower()):
            if item.target_species and not self._mega:
                continue
            if item.target_species:
                (compatible if item.target_species.lower() == self._species else incompatible).append(item)
            else:
                others.append(item)
        return compatible, others, incompatible

    def _refresh(self) -> None:
        compatible, others, incompatible = self._candidates()
        for key, tile in self._category_tiles.items():
            tile.bgcolor = Palette.SURFACE_3 if key == self._category else None
        rows: list[ft.Control] = [self._row(i, compatible=True) for i in compatible] + [self._row(i) for i in others[:_MAX_ROWS]]
        if incompatible:
            if self._show_incompatible:
                rows.append(ft.Text("Mega Stones for other species", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT))
                rows += [self._row(i, incompatible=True) for i in incompatible]
            else:
                rows.append(ft.TextButton(f"Show {len(incompatible)} Mega Stones for other species", on_click=lambda _e: self._toggle_incompatible()))
        if not rows:
            rows.append(EmptyState(ft.Icons.SEARCH_OFF, "No items match", "Try another search or switch off Champions-legal only."))
        self._list.controls = rows
        if is_mounted(self):
            self.update()

    def _toggle_incompatible(self) -> None:
        self._show_incompatible = not self._show_incompatible
        self._refresh()

    def _row(self, item: ItemRecord, *, compatible: bool = False, incompatible: bool = False) -> ft.Control:
        badges: list[ft.Control] = []
        if incompatible:
            badges.append(StatusChip(f"Needs {item.target_species.title()}", "error", icon=ft.Icons.BLOCK))
        elif compatible:
            form = (item.target_form or "mega").replace("-", " ").title()
            badges.append(StatusChip(f"Unlocks {form}", "info", icon=ft.Icons.BOLT))
        elif not item.is_champions_legal:
            badges.append(StatusChip("Not Champions-legal", "warning", icon=ft.Icons.WARNING_AMBER_OUTLINED))
        for stat, mult in (item.stat_modifiers or {}).items():
            chip = StatusChip(f"{round((mult - 1) * 100):+d}% {STAT_LABELS.get(stat, stat)}", "neutral")
            chip._label.color = STAT_COLORS.get(stat, Palette.ON_SURFACE_VARIANT)
            badges.append(chip)
        leading = (
            ft.Image(src=item.sprite_url, width=32, height=32, fit=ft.BoxFit.CONTAIN, error_content=ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=IconSize.MD, color=Palette.DISABLED))
            if item.sprite_url else ft.Icon(ft.Icons.BOLT if item.target_species else ft.Icons.DIAMOND_OUTLINED, size=IconSize.MD, color=Palette.ON_SURFACE_VARIANT)
        )
        return ft.Container(
            content=ft.Row(
                spacing=Space.MD,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    leading,
                    ft.Column(spacing=2, tight=True, expand=True, controls=[
                        ft.Text(item.display_name, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.DISABLED if incompatible else Palette.ON_SURFACE),
                        ft.Text(item.short_effect or "", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ]),
                    ft.Row(spacing=Space.XS, tight=True, wrap=True, controls=badges),
                ],
            ),
            padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS),
            border_radius=Radius.SM,
            opacity=0.55 if incompatible else 1.0,
            on_click=None if incompatible else (lambda _e, cid=item.canonical_id: self._on_pick(cid)),
            ink=not incompatible,
        )

    def _pick_first(self) -> None:
        compatible, others, _ = self._candidates()
        first = (compatible + others)[:1]
        if first:
            self._on_pick(first[0].canonical_id)
