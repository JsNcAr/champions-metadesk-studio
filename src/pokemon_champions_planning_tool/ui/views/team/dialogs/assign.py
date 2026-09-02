"""Assign dialog: pick a box entry for a slot, with search and a planned toggle."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import flet as ft

from .....domain.entities.box_entry import BoxEntry
from ....components import EmptyState
from ....components.inputs import SEARCH_FIELD_STYLE
from ....components.pokemon import BstPill, IdentityRow
from ....tasks import is_mounted
from ....theme import Palette, Radius, Space

_MAX_ROWS = 60


class AssignDialog(ft.AlertDialog):
    def __init__(
        self,
        *,
        slot: int,
        entries: list[BoxEntry],
        assigned: set[UUID],
        on_pick: Callable[[UUID], None],
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(modal=True)
        self._entries = entries
        self._assigned = assigned
        self._on_pick = on_pick
        self._on_close = on_close
        self._include_planned = False

        self._search = ft.TextField(**SEARCH_FIELD_STYLE, hint_text="Search by name, type or tag…", prefix_icon=ft.Icons.SEARCH, autofocus=True, dense=True,
                                    on_change=lambda _e: self._refresh(), on_submit=lambda _e: self._pick_first())
        self._planned = ft.Switch(label="Include planned", value=False, on_change=lambda e: self._set_planned(bool(e.control.value)))
        self._list = ft.ListView(spacing=Space.XS, height=380)
        self.title = ft.Text(f"Assign to slot {slot}")
        self.content = ft.Container(
            width=520,
            content=ft.Column(spacing=Space.MD, tight=True, controls=[
                ft.Row(spacing=Space.MD, controls=[ft.Container(content=self._search, expand=True), self._planned]),
                self._list,
            ]),
        )
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: self._on_close())]
        self.actions_alignment = ft.MainAxisAlignment.END
        self.on_dismiss = lambda _e: None
        self._refresh()

    def _set_planned(self, value: bool) -> None:
        self._include_planned = value
        self._refresh()

    def _matches(self) -> list[BoxEntry]:
        q = (self._search.value or "").strip().lower()
        out = []
        for e in self._entries:
            if e.is_planned and not self._include_planned:
                continue
            if q and not (q in e.pokemon.display_name.lower() or any(q in t.lower() for t in e.pokemon.types) or any(q in t.lower() for t in e.tags)):
                continue
            out.append(e)
        return out[:_MAX_ROWS]

    def _refresh(self) -> None:
        matches = self._matches()
        rows: list[ft.Control] = []
        for e in matches:
            on_team = e.box_entry_id in self._assigned
            trailing = ft.Row(spacing=Space.SM, tight=True, controls=[
                BstPill(e.pokemon.total),
                *([ft.Text("on this team", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)] if on_team else []),
            ])
            row = IdentityRow(name=e.pokemon.display_name, form=e.pokemon.form_name, types=e.pokemon.types, sprite_url=e.pokemon.sprite_url, trailing=trailing)
            rows.append(
                ft.Container(
                    content=row,
                    padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=Space.XS),
                    border_radius=Radius.SM,
                    opacity=0.5 if on_team else 1.0,
                    on_click=(lambda _e, eid=e.box_entry_id: self._on_pick(eid)) if not on_team else None,
                    ink=not on_team,
                )
            )
        if not rows:
            rows.append(EmptyState(ft.Icons.SEARCH_OFF, "No matches", "Add the Pokémon to your box first, or include planned entries."))
        self._list.controls = rows
        if is_mounted(self._list):
            self._list.update()

    def _pick_first(self) -> None:
        for e in self._matches():
            if e.box_entry_id not in self._assigned:
                self._on_pick(e.box_entry_id)
                return
