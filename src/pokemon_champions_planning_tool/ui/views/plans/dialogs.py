"""Plans dialogs: a paste (new plan, or a plan's opponent) and a rival preset picker.

Both only collect input; the view does the parsing on a worker and the saving.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import flet as ft

from ...tasks import is_mounted
from ...theme import Accent, Palette, Radius, Space, alpha
from ..calc.state import RivalTeam
from .components import species_sprite

PASTE_HINT = "Showdown text of their six, or a pokepast.es link"


class PasteDialog(ft.AlertDialog):
    """Name + paste. ``on_submit(name, text)`` starts the import; the view reports back with
    ``set_busy`` / ``set_error``, and closes the dialog when it worked."""

    def __init__(self, *, title: str, submit_label: str, on_submit: Callable[[str, str], None], on_cancel: Callable[[], None],
                 name: str | None = "", text: str = "", note: str | None = None) -> None:
        super().__init__(modal=True, scrollable=True)
        self._on_submit = on_submit
        self._name = ft.TextField(label="Plan name", value=name or "", hint_text="e.g. Big Six, Raptor (Sand)…", autofocus=True,
                                  visible=name is not None)
        self._text = ft.TextField(label="Their team", value=text, hint_text=PASTE_HINT, multiline=True, min_lines=10, max_lines=16, text_size=13,
                                  autofocus=name is None)
        self._error = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ERROR, visible=False)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._submit = ft.FilledButton(submit_label, on_click=lambda _e: self._fire())
        controls: list[ft.Control] = [self._name, self._text]
        if note:
            controls.insert(0, ft.Text(note, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT))
        controls.append(ft.Row(spacing=Space.SM, controls=[self._spinner, self._error]))
        self.title = ft.Text(title)
        self.content = ft.Container(width=560, content=ft.Column(spacing=Space.MD, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=controls))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel()), self._submit]
        self.actions_alignment = ft.MainAxisAlignment.END

    @property
    def name(self) -> str:
        return (self._name.value or "").strip()

    @property
    def text(self) -> str:
        return (self._text.value or "").strip()

    def _fire(self) -> None:
        if not self.text:
            self.set_error("Paste their team, or a pokepast.es link")
            return
        self._on_submit(self.name, self.text)

    def set_busy(self, busy: bool) -> None:
        self._spinner.visible = busy
        self._submit.disabled = busy
        if busy:
            self._error.visible = False
        self._refresh()

    def set_error(self, message: str) -> None:
        self._spinner.visible = False
        self._submit.disabled = False
        self._error.value = message
        self._error.visible = True
        self._refresh()

    def _refresh(self) -> None:
        if is_mounted(self):
            self.update()


class PresetPickerDialog(ft.AlertDialog):
    """Your saved rival presets (Calc); clicking one makes a plan against it."""

    def __init__(self, presets: Sequence[RivalTeam], catalogs: Any, *, on_pick: Callable[[RivalTeam], None], on_cancel: Callable[[], None]) -> None:
        super().__init__(modal=False, scrollable=True)
        rows: list[ft.Control] = []
        for team in presets:
            rows.append(ft.Container(
                content=ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Column(spacing=2, tight=True, expand=True, controls=[
                        ft.Text(team.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(team.source or "Rival preset", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ]),
                    ft.Row(spacing=0, controls=[species_sprite(m.pokemon.species, catalogs, size=28) for m in team.members[:6]]),
                ]),
                padding=Space.SM, border_radius=Radius.SM, ink=True,
                on_click=lambda _e, t=team: on_pick(t),
                on_hover=_hover,
                data=team.rival_team_id,
            ))
        if not rows:
            rows = [ft.Text("No rival presets yet. Save one in Calc (Rival team ▸ Load team…) or from a Meta team.",
                            theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
        self.title = ft.Text("Plan against a rival preset")
        self.content = ft.Container(width=560, content=ft.Column(spacing=2, tight=True, controls=rows))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_cancel())]
        self.actions_alignment = ft.MainAxisAlignment.END


def _hover(e: ft.ControlEvent) -> None:
    on = getattr(e, "data", None) in ("true", True)
    e.control.bgcolor = alpha(Accent.PLANS, 0.10) if on else None
    if is_mounted(e.control):
        e.control.update()


__all__ = ["PASTE_HINT", "PasteDialog", "PresetPickerDialog"]
