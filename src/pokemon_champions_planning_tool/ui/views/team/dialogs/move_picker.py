"""Move picker: a species' Champions-legal moves, ranked by tournament usage.

Illegal moves are hidden unless "Show all moves" is on (a team-builder option); then
they are listed greyed with a warning and can still be chosen, in case the catalogue is
wrong about one. Typing a name that matches nothing offers to use it as typed.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from .....domain.moves import MoveInfo, move_key
from ....components import EmptyState, StatusChip
from ....components.inputs import SEARCH_FIELD_STYLE
from ....components.pokemon import TypeChip
from ....tasks import is_mounted
from ....theme import IconSize, Palette, Radius, Space
from ..store import MoveOptions

_MAX_ROWS = 120
_CATEGORY_ICONS = {"physical": ft.Icons.FITNESS_CENTER, "special": ft.Icons.AUTO_AWESOME, "status": ft.Icons.CHANGE_CIRCLE_OUTLINED}


class MovePickerDialog(ft.AlertDialog):
    def __init__(
        self,
        *,
        species_label: str,
        options: MoveOptions,
        current: str | None,
        show_all: bool,
        on_pick: Callable[[str | None], None],
        on_close: Callable[[], None],
        on_show_all: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(modal=True)
        self._options = options
        self._current = (current or "").strip()
        self._show_all = show_all
        self._on_pick = on_pick
        self._on_close = on_close
        self._on_show_all = on_show_all

        self._search = ft.TextField(**SEARCH_FIELD_STYLE, hint_text="Search moves…", prefix_icon=ft.Icons.SEARCH, autofocus=True, dense=True, expand=True,
                                    on_change=lambda _e: self._refresh(), on_submit=lambda _e: self._pick_first())
        self._switch = ft.Switch(label="Show all moves", value=show_all, tooltip="List moves outside the Champions learnset too (with a warning)",
                                 on_change=lambda e: self._toggle_show_all(bool(e.control.value)))
        self._caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._list = ft.ListView(spacing=Space.XS, expand=True)
        self._first: str | None = None

        self.title = ft.Text(f"Choose move · {species_label}")
        self.content = ft.Container(
            width=640,
            height=560,
            content=ft.Column(
                spacing=Space.MD,
                expand=True,
                controls=[ft.Row(spacing=Space.MD, controls=[self._search, self._switch]), self._caption, self._list],
            ),
        )
        self.actions = [
            ft.TextButton("Clear move", icon=ft.Icons.CLOSE, visible=bool(self._current), on_click=lambda _e: self._on_pick(None)),
            ft.Container(expand=True),
            ft.TextButton("Cancel", on_click=lambda _e: self._on_close()),
        ]
        self.actions_alignment = ft.MainAxisAlignment.END
        self._refresh()

    # -- state -------------------------------------------------------------------------------------

    def _toggle_show_all(self, value: bool) -> None:
        self._show_all = value
        if self._on_show_all is not None:
            self._on_show_all(value)
        self._refresh()

    def _rank(self, move: MoveInfo) -> tuple[float, str]:
        return (-self._options.usage.get(move.move_id, 0.0), move.name.lower())

    def _candidates(self) -> tuple[list[MoveInfo], list[MoveInfo]]:
        q = (self._search.value or "").strip().lower()
        qk = move_key(q)

        def match(m: MoveInfo) -> bool:
            return not q or q in m.name.lower() or (qk and qk in m.move_id)

        legal = sorted((m for m in self._options.legal if match(m)), key=self._rank)
        others = sorted((m for m in self._options.others if match(m)), key=self._rank) if self._show_all else []
        return legal, others

    def _refresh(self) -> None:
        legal, others = self._candidates()
        rows: list[ft.Control] = [self._row(m, legal=True) for m in legal[:_MAX_ROWS]]
        if others:
            rows.append(ft.Text("Not in the Champions learnset", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.WARNING))
            rows += [self._row(m, legal=False) for m in others[:_MAX_ROWS]]
        q = (self._search.value or "").strip()
        exact = any(move_key(m.name) == move_key(q) for m in legal + others)
        if q and not exact:
            rows.append(
                ft.Container(
                    content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                        ft.Icon(ft.Icons.EDIT, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT),
                        ft.Text(f"Use “{q}” as typed", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, expand=True),
                        StatusChip("Unchecked", "warning", icon=ft.Icons.WARNING_AMBER_ROUNDED),
                    ]),
                    padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM), border_radius=Radius.SM, ink=True,
                    on_click=lambda _e, name=q: self._on_pick(name),
                )
            )
        if not rows:
            rows.append(EmptyState(ft.Icons.SEARCH_OFF, "No moves match", "Try another spelling, or switch on Show all moves."))
        self._first = (legal[0].name if legal else (others[0].name if others else (q or None)))
        self._list.controls = rows
        known = self._options.known
        if not known:
            self._caption.value = "No Champions learnset for this species yet — every move is listed unchecked."
        else:
            hidden = len(self._options.others)
            self._caption.value = f"{len(self._options.legal)} legal moves · ranked by tournament usage" + ("" if self._show_all or not hidden else f" · {hidden} others hidden")
        if is_mounted(self):
            self.update()

    def _pick_first(self) -> None:
        if self._first:
            self._on_pick(self._first)

    def _row(self, move: MoveInfo, *, legal: bool) -> ft.Control:
        usage = self._options.usage.get(move.move_id, 0.0)
        stats = [ft.Text((move.category or "?").capitalize(), theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, width=64)]
        stats.append(ft.Text(str(move.power) if move.power else "—", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, width=36, text_align=ft.TextAlign.RIGHT, tooltip="Power"))
        stats.append(ft.Text(f"{move.accuracy}%" if move.accuracy else "—", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, width=44, text_align=ft.TextAlign.RIGHT, tooltip="Accuracy"))
        trailing: list[ft.Control] = []
        if usage >= 0.005:
            trailing.append(StatusChip(f"{usage:.0%}", "info", tooltip=f"Carried by {usage:.0%} of this species' tournament rosters"))
        if not legal:
            trailing.append(ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=IconSize.SM, color=Palette.WARNING, tooltip="Not in the Champions learnset"))
        selected = move_key(move.name) == move_key(self._current)
        return ft.Container(
            content=ft.Row(
                spacing=Space.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    TypeChip(move.type or "unknown", size="sm"),
                    ft.Icon(_CATEGORY_ICONS.get((move.category or "").lower(), ft.Icons.HELP_OUTLINE), size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT),
                    ft.Text(move.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE if legal else Palette.ON_SURFACE_VARIANT, expand=True, tooltip=move.short_desc or move.name),
                    *stats,
                    *trailing,
                ],
            ),
            padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.XS),
            border_radius=Radius.SM,
            bgcolor=Palette.SURFACE_3 if selected else None,
            opacity=1.0 if legal else 0.75,
            ink=True,
            on_click=lambda _e, name=move.name: self._on_pick(name),
        )


__all__ = ["MovePickerDialog"]
