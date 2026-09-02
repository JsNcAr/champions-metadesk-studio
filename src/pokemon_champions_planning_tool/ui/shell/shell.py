"""Application shell: navigation rail, content host, keyboard shortcuts.

The shell is the only place that calls ``page.update()``. Views are registered by key
and built lazily on first navigation; the shell keeps the instance afterwards so
switching back is free.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import flet as ft

from ..context import AppContext
from ..events import NAVIGATE
from ..tasks import is_mounted
from ..theme import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH, IconSize, Layout, Palette, Radius, Space

ViewFactory = Callable[[], ft.Control]


@dataclass
class _ViewEntry:
    key: str
    label: str
    icon: str
    selected_icon: str
    factory: ViewFactory
    on_activate: Callable[[], None] | None = None
    control: ft.Control | None = field(default=None)

    def instance(self) -> ft.Control:
        if self.control is None:
            self.control = self.factory()
        return self.control


# Keys reachable with Ctrl+<digit>, in rail order.
_DIGIT_KEYS = ("1", "2", "3", "4", "5", "6", "7", "8", "9")


class AppShell(ft.Row):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(
            spacing=0,
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.ctx = ctx
        self._entries: dict[str, _ViewEntry] = {}
        self._order: list[str] = []
        self._current: str | None = None
        self._open_settings: Callable[[], None] | None = None

        self._settings_button = ft.IconButton(
            icon=ft.Icons.SETTINGS_OUTLINED,
            icon_size=IconSize.LG,
            tooltip="Settings (Ctrl+,)",
            on_click=lambda _e: self.open_settings(),
        )
        self._help_button = ft.IconButton(
            icon=ft.Icons.HELP_OUTLINE,
            icon_size=IconSize.LG,
            tooltip="Help (F1)",
            on_click=lambda _e: self.open_help(),
        )
        self.compact = False
        self.rail = ft.NavigationRail(
            destinations=[],
            selected_index=0,
            extended=False,
            label_type=ft.NavigationRailLabelType.ALL,
            min_width=Layout.RAIL_WIDTH,
            group_alignment=-1.0,
            leading=ft.Container(
                content=ft.Icon(ft.Icons.CATCHING_POKEMON, color=Palette.PRIMARY, size=IconSize.LG),
                width=40,
                height=40,
                alignment=ft.Alignment.CENTER,
                bgcolor=Palette.SURFACE_2,
                border_radius=Radius.MD,
                margin=ft.Margin.only(top=Space.MD, bottom=Space.SM),
            ),
            trailing=ft.Container(
                content=ft.Column(spacing=0, tight=True, controls=[self._help_button, self._settings_button]),
                margin=ft.Margin.only(bottom=Space.MD),
            ),
            on_change=self._on_rail_change,
        )
        self.host = ft.Container(expand=True, padding=Space.PAGE_PADDING)
        self.controls = [
            self.rail,
            ft.VerticalDivider(width=1, thickness=1, color=Palette.OUTLINE_VARIANT),
            self.host,
        ]

        ctx.bus.on(NAVIGATE, self.navigate)
        ctx.page.on_keyboard_event = self._on_key
        ctx.page.on_resize = self._on_resize

    # -- registration -----------------------------------------------------------------

    def register_view(
        self,
        key: str,
        *,
        label: str,
        icon: str,
        selected_icon: str,
        factory: ViewFactory | None = None,
        control: ft.Control | None = None,
        on_activate: Callable[[], None] | None = None,
        in_rail: bool = True,
    ) -> None:
        """Register a view. Pass either a ready ``control`` or a ``factory`` that builds
        it on first visit. ``in_rail=False`` registers a page reachable by key only
        (Settings lives in the rail's trailing slot, not among the destinations)."""
        if (factory is None) == (control is None):
            raise ValueError("register_view needs exactly one of factory or control")
        entry = _ViewEntry(
            key=key,
            label=label,
            icon=icon,
            selected_icon=selected_icon,
            factory=factory or (lambda: control),  # type: ignore[return-value]
            on_activate=on_activate,
            control=control,
        )
        self._entries[key] = entry
        if in_rail:
            self._order.append(key)
            self.rail.destinations.append(
                ft.NavigationRailDestination(icon=icon, selected_icon=selected_icon, label=label)
            )

    def register_settings(self, open_settings: Callable[[], None]) -> None:
        self._open_settings = open_settings

    # -- navigation -------------------------------------------------------------------

    @property
    def current(self) -> str | None:
        return self._current

    def navigate(self, key: str) -> None:
        entry = self._entries[key]
        self.host.content = entry.instance()
        self.rail.selected_index = self._order.index(key) if key in self._order else None
        self._current = key
        self._apply_width(self.page_size()[0])
        self._forward_size(entry.control)
        if entry.on_activate is not None:
            entry.on_activate()
        self._update_if_mounted()

    def open_settings(self) -> None:
        if self._open_settings is not None:
            self._open_settings()

    def _on_rail_change(self, e: ft.ControlEvent) -> None:
        index = int(e.control.selected_index or 0)
        if 0 <= index < len(self._order):
            self.navigate(self._order[index])

    def open_help(self) -> None:
        from ..help import HelpDialog

        page = self.ctx.page
        page.show_dialog(HelpDialog(on_close=page.pop_dialog))

    def _on_key(self, e: ft.KeyboardEvent) -> None:
        if e.key == "Escape" and self._close_top_dialog():
            return
        if e.key == "F1" or (e.ctrl and e.key == "/"):
            self.open_help()
            return
        if e.ctrl and e.key in _DIGIT_KEYS:
            index = int(e.key) - 1
            if index < len(self._order):
                self.navigate(self._order[index])
            return
        if e.ctrl and e.key == ",":
            self.open_settings()
            return
        # Anything else goes to the current view if it declares handle_key(event) -> bool.
        entry = self._entries.get(self._current) if self._current else None
        handler = getattr(entry.control, "handle_key", None) if entry and entry.control is not None else None
        if callable(handler):
            handler(e)

    # -- window size -----------------------------------------------------------------------

    def page_size(self) -> tuple[float, float]:
        page = self.ctx.page
        window = getattr(page, "window", None)
        width = getattr(page, "width", None) or getattr(window, "width", None) or DEFAULT_WINDOW_WIDTH
        height = getattr(page, "height", None) or getattr(window, "height", None) or DEFAULT_WINDOW_HEIGHT
        return float(width), float(height)

    def _forward_size(self, control: ft.Control | None) -> None:
        """Views that declare ``handle_resize(width, height)`` size their grids from it."""
        handler = getattr(control, "handle_resize", None)
        if callable(handler):
            handler(*self.page_size())

    def _apply_width(self, width: float) -> None:
        """Compact rail (icons only) and tighter page padding below the compact breakpoint."""
        compact = width < Layout.BREAKPOINT_COMPACT
        if compact == self.compact:
            return
        self.compact = compact
        self.rail.label_type = ft.NavigationRailLabelType.NONE if compact else ft.NavigationRailLabelType.ALL
        self.rail.min_width = Layout.RAIL_WIDTH_COMPACT if compact else Layout.RAIL_WIDTH
        self.host.padding = Space.LG if compact else Space.PAGE_PADDING

    def _on_resize(self, e) -> None:
        width, _height = self.page_size()
        self._apply_width(width)
        # Every built view gets the size, so a hidden one is already right when shown.
        for entry in self._entries.values():
            if entry.control is not None:
                self._forward_size(entry.control)
        self._update_if_mounted()

    def _close_top_dialog(self) -> bool:
        """Modal dialogs ignore Escape on their own; close the topmost open one here."""
        page = self.ctx.page
        stack = getattr(getattr(page, "_dialogs", None), "controls", None)
        if stack is None:
            stack = getattr(page, "dialogs", None) or []
        if not any(getattr(dlg, "open", True) for dlg in stack):
            return False
        return page.pop_dialog() is not None

    def _update_if_mounted(self) -> None:
        # Before page.add the controls have no page; Flet auto-updates after the
        # event that mounted them. Only an explicit navigate() after mount needs this.
        if is_mounted(self):
            self.ctx.page.update()
