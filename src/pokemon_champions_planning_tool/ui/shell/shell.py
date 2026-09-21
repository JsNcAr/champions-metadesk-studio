"""Application shell: navigation rail, content host, keyboard shortcuts.

Views are registered by key and built lazily (or preloaded while idle). Once built they
stay mounted in a stack and are layered rather than swapped — see ``AppShell.deck`` —
so switching views crossfades and never re-sends or re-walks a view that did not change.
The shell updates only the controls a switch touches; ``page.update()`` is reserved for
changes that span the layout (a resize, a breakpoint).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import flet as ft

from ..components.banner import InlineBanner
from ..context import AppContext
from ..events import NAVIGATE
from ..tasks import is_mounted
from ..theme import DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH, IconSize, Layout, Motion, Palette, Radius, Space

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


# How long after un-hiding a view its opacity is raised. A hidden view has no widget on
# the client, so un-hiding creates it; if the raise lands before that first build, the
# widget is born fully opaque and there is nothing to animate. A frame or so of delay lets
# it be built at 0 — a raise arriving mid-build simply waits for the build to finish.
_FADE_START_S = 0.06

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
        # Views stay mounted in this stack and are layered rather than swapped.
        #
        # Swapping the host's content detached the old view, so returning to it re-sent its
        # whole control tree (about 1 MB for a full Box) and the client rebuilt it. And any
        # update that *contains* a view makes Flet walk every node of it — ~370 ms for a
        # 250-card Box even when nothing in it changed. So: every view has a slot made at
        # registration (the stack's child list never changes after mount), the first view
        # is a base layer that navigation never touches, and the others are opaque
        # overlays that fade in and out above it. A switch updates only the small slots
        # involved, and the fade is a real crossfade.
        self.deck = ft.Stack(expand=True, controls=[])
        self._slots: dict[str, ft.Container] = {}
        self.host = ft.Container(expand=True, padding=Space.PAGE_PADDING, content=self.deck)
        # A 2px bar along the top of the content, shown only while a view that has not
        # been built yet is being built. Warm switches are instant and never show it.
        self.progress = ft.ProgressBar(value=None, bar_height=2, color=Palette.PRIMARY,
                                       bgcolor=ft.Colors.TRANSPARENT, visible=False)
        self._pending: str | None = None
        # Spans every view: app-wide state such as the first-run catalogue download, which
        # no single view owns. Takes no space while hidden.
        self.status = InlineBanner(visible=False)
        self.status.margin = ft.Margin.only(left=Space.PAGE_PADDING, right=Space.PAGE_PADDING, top=Space.MD)
        self.controls = [
            self.rail,
            ft.VerticalDivider(width=1, thickness=1, color=Palette.OUTLINE_VARIANT),
            ft.Column(expand=True, spacing=0, controls=[self.progress, self.status, self.host]),
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
        slot = ft.Container(
            content=control, left=0, top=0, right=0, bottom=0,
            visible=False, opacity=0.0, bgcolor=Palette.BG,
            animate_opacity=ft.Animation(Motion.NORMAL_MS, Motion.CURVE),
        )
        self._slots[key] = slot
        self.deck.controls.append(slot)
        if in_rail:
            self._order.append(key)
            self.rail.destinations.append(
                ft.NavigationRailDestination(icon=icon, selected_icon=selected_icon, label=label)
            )

    def set_status(self, message: str, kind: str = "info", **kwargs) -> None:
        """Show the app-wide banner above the content."""
        self.status.show(message, kind, **kwargs)  # type: ignore[arg-type]
        self._update(self.status)

    def clear_status(self) -> None:
        self.status.hide()
        self._update(self.status)

    def register_settings(self, open_settings: Callable[[], None]) -> None:
        self._open_settings = open_settings

    # -- navigation -------------------------------------------------------------------

    @property
    def current(self) -> str | None:
        return self._current

    def get_view(self, key: str) -> ft.Control | None:
        entry = self._entries.get(key)
        return entry.instance() if entry else None

    def navigate(self, key: str) -> None:
        if self._current == key:
            return
        entry = self._entries[key]
        previous = self._current
        self.rail.selected_index = self._order.index(key) if key in self._order else None
        self._current = key
        if entry.control is None and is_mounted(self):
            # Not built yet (clicked before the idle prewarm reached it): building takes
            # a noticeable moment on the UI loop. Acknowledge the click first — rail moved,
            # bar showing — and build on the next tick instead of freezing on the old view.
            self._pending = key
            self.progress.visible = True
            self._update(self.rail, self.progress)

            async def _build() -> None:
                if self._pending != key:   # another view was chosen meanwhile
                    return
                self._pending = None
                self._show(entry, previous)

            self.ctx.page.run_task(_build)
            return
        self._pending = None
        self._show(entry, previous)

    @property
    def current_control(self) -> ft.Control | None:
        entry = self._entries.get(self._current) if self._current else None
        return entry.control if entry else None

    def _base_key(self) -> str | None:
        return next(iter(self._slots), None)

    def _fill(self, entry: _ViewEntry) -> tuple[ft.Container, bool]:
        """The view's slot, with the view built and placed in it. True when just placed."""
        slot = self._slots[entry.key]
        if slot.content is None:
            slot.content = entry.instance()
            return slot, True
        return slot, False

    def preload(self, key: str, *, activate: bool = False) -> None:
        """Build a view and mount it hidden, so its first visit sends nothing new.

        Meant for idle time: mounting is when a view's control tree goes to the client,
        and only this view's slot is updated to do it. ``activate`` also runs the view's
        on-activate hook — for these views an idempotent load — so the data is in place
        before the first visit instead of being fetched on the click.
        """
        entry = self._entries.get(key)
        if entry is None:
            return
        slot, placed = self._fill(entry)
        if placed:
            self._forward_size(entry.control)
            self._update(slot)
        if activate and entry.on_activate is not None:
            entry.on_activate()

    def _update(self, *controls: ft.Control) -> None:
        for control in controls:
            if is_mounted(control):
                control.update()

    def _later(self, seconds: float, fn: Callable[[], None]) -> None:
        if not is_mounted(self):
            fn()
            return

        async def _run() -> None:
            import asyncio
            await asyncio.sleep(seconds)
            fn()

        self.ctx.page.run_task(_run)

    def _show(self, entry: _ViewEntry, previous: str | None = None) -> None:
        slot, placed = self._fill(entry)
        if placed:
            self._forward_size(entry.control)
        self.progress.visible = False
        if self._apply_width(self.page_size()[0]):
            self._update_if_mounted()   # breakpoint crossed: the rail and padding change
        self._update(self.rail, self.progress)

        base = self._base_key()
        old = self._slots.get(previous) if previous and previous != entry.key else None
        keys = list(self._slots)
        fade = Motion.NORMAL_MS / 1000

        # Whichever of the two views is higher in the stack animates: an arriving view
        # above fades in over the old one; an arriving view below appears under it while
        # the old one fades away. Either way it is a crossfade, and the base (first slot)
        # sits under everything and is never updated by a switch.
        arriving_above = entry.key != base and (
            old is None or previous == base or keys.index(entry.key) > keys.index(previous)
        )
        if entry.key == base:
            if not slot.visible:          # first time only: the base is never hidden again
                slot.visible, slot.opacity = True, 1.0
                self._update(slot)
        elif arriving_above:
            slot.visible, slot.opacity = True, 0.0
            self._update(slot)
            self._later(_FADE_START_S, lambda: self._raise(entry.key))
        else:
            slot.visible, slot.opacity = True, 1.0
            self._update(slot)
        if old is not None and previous != base:
            if not arriving_above:
                old.opacity = 0.0
                self._update(old)
            self._later(fade, lambda key=previous: self._retire(key))

        if entry.on_activate is not None:
            entry.on_activate()

    def _raise(self, key: str) -> None:
        slot = self._slots[key]
        if self._current == key and slot.visible:
            slot.opacity = 1.0
            self._update(slot)

    def _retire(self, key: str) -> None:
        """Take a faded-out overlay out of layout and hit-testing, unless it came back."""
        if self._current == key or key == self._base_key():
            return
        slot = self._slots[key]
        if slot.visible:
            slot.visible, slot.opacity = False, 0.0
            self._update(slot)

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

    def _apply_width(self, width: float) -> bool:
        """Compact rail (icons only) and tighter page padding below the compact breakpoint."""
        compact = width < Layout.BREAKPOINT_COMPACT
        if compact == self.compact:
            return False
        self.compact = compact
        self.rail.label_type = ft.NavigationRailLabelType.NONE if compact else ft.NavigationRailLabelType.ALL
        self.rail.min_width = Layout.RAIL_WIDTH_COMPACT if compact else Layout.RAIL_WIDTH
        self.host.padding = Space.LG if compact else Space.PAGE_PADDING
        return True

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
