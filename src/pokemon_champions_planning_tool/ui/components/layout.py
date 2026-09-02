"""Responsive split: main content beside a side panel, or the panel overlaid when narrow.

Wide (≥ Layout.BREAKPOINT_NARROW): a Row — main expands, the panel keeps its width.
Narrow: a Stack — main fills it and the panel slides over the right edge with a shadow,
so a 1000px window still shows the full grid and the panel on demand. The same panel
control is reused in both modes; only the arrangement changes.
"""

from __future__ import annotations

import flet as ft

from ..theme import OVERLAY_SHADOW, Space


class SplitPane(ft.Container):
    def __init__(self, main: ft.Control, panel: ft.Control, *, gap: int = Space.LG) -> None:
        super().__init__(expand=True)
        self.main = main
        self.panel = panel
        self.gap = gap
        self.narrow = False
        self._main_wide = ft.Container(content=main, expand=True)
        self._main_narrow = ft.Container(content=main, left=0, top=0, right=0, bottom=0)
        self._row = ft.Row(spacing=gap, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH, controls=[self._main_wide, panel])
        self._stack = ft.Stack(expand=True, fit=ft.StackFit.EXPAND, controls=[self._main_narrow, panel])
        self.content = self._row

    def set_narrow(self, narrow: bool) -> bool:
        """Switch mode; returns True when it changed (caller decides whether to update)."""
        if narrow == self.narrow:
            return False
        self.narrow = narrow
        # A control may only live in one parent at a time: move it explicitly.
        self._main_wide.content = None if narrow else self.main
        self._main_narrow.content = self.main if narrow else None
        self._row.controls = [self._main_wide] + ([] if narrow else [self.panel])
        self._stack.controls = [self._main_narrow] + ([self.panel] if narrow else [])
        if narrow:
            self.panel.right, self.panel.top, self.panel.bottom = 0, 0, 0
            self.panel.shadow = OVERLAY_SHADOW
        else:
            self.panel.right = self.panel.top = self.panel.bottom = None
            self.panel.shadow = None
        self.content = self._stack if narrow else self._row
        return True


__all__ = ["SplitPane"]
