"""Live tournament-sync feedback: a caption and a bar that follow SyncProgress."""

from __future__ import annotations

import flet as ft

from ..tasks import is_mounted
from ..theme import Palette, Space


class SyncIndicator(ft.Row):
    """``⟳ Fetching standings 12 of 40 · 1,240 teams`` with a determinate bar.

    Hidden until a sync reports progress; shows the final summary for a while after.
    """

    def __init__(self, *, width: int = 260) -> None:
        super().__init__(spacing=Space.SM, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, visible=False)
        self._ring = ft.ProgressRing(width=14, height=14, stroke_width=2)
        self._text = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._bar = ft.ProgressBar(value=None, bar_height=3, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT, width=width)
        self.controls = [self._ring, ft.Column(spacing=2, tight=True, controls=[self._text, self._bar])]
        self.phase = "idle"

    def update_from(self, progress) -> None:
        self.phase = progress.phase
        running = progress.running
        self.visible = True
        self._ring.visible = running
        self._bar.visible = running
        self._bar.value = progress.fraction
        text = progress.message
        if running and progress.teams_added:
            text += f" · {progress.teams_added:,} teams"
        self._text.value = text
        self._text.color = Palette.ERROR if progress.phase == "error" else (Palette.SUCCESS if progress.phase == "done" else Palette.ON_SURFACE_VARIANT)
        if is_mounted(self):
            self.update()

    def hide(self) -> None:
        self.visible = False
        if is_mounted(self):
            self.update()
