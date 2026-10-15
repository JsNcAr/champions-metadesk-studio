"""Settings › About › Version: this version, whether a newer one is out, and the daily check."""

from __future__ import annotations

from datetime import datetime

import flet as ft

from .... import __version__
from ....services import update_check
from ... import events
from ...context import AppContext
from ...format import relative_time
from ...tasks import is_mounted, open_url
from ...theme import Palette, Space
from .store import SettingsStore


class UpdateRow(ft.Column):
    def __init__(self, ctx: AppContext, store: SettingsStore) -> None:
        super().__init__(spacing=Space.XS, tight=True)
        self.ctx = ctx
        self.store = store
        self._release: update_check.Release | None = None
        self._line = ft.Text(__version__, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, selectable=True)
        self._download = ft.TextButton("Download", icon=ft.Icons.DOWNLOAD, visible=False, on_click=lambda _e: self._open())
        self._check = ft.TextButton("Check now", icon=ft.Icons.REFRESH, on_click=lambda _e: self.check_now())
        self._spinner = ft.ProgressRing(width=14, height=14, stroke_width=2, visible=False)
        self._daily = ft.Switch(label="Check for new versions once a day", value=ctx.prefs.get(update_check.PREF_ENABLED, True) is not False,
                                on_change=lambda e: ctx.prefs.set(update_check.PREF_ENABLED, bool(e.control.value)))
        self.controls = [
            self._line,
            ft.Row(spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                   controls=[self._download, self._check, self._spinner]),
            self._daily,
            ft.Text("The check is one request a day to GitHub, carrying only the app's name and version.",
                    theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
        ]
        ctx.bus.on(events.UPDATE_CHECKED, lambda _release: self.refresh())

    def refresh(self) -> None:
        """Read what the last check saw (no request)."""
        def done(result) -> None:
            latest, checked = result
            self.show(latest, checked)

        self.ctx.run_in_background(self.store.update_status, on_done=done, on_error=lambda _exc: None)

    def show(self, latest: update_check.Release | None, checked: str | None) -> None:
        newer = latest is not None and update_check.is_newer(latest.version)
        self._release = latest if newer else None
        if newer:
            self._line.value = f"{__version__} · version {latest.version} is available"
            self._line.color = Palette.WARNING
        elif checked:
            try:
                when = relative_time(datetime.fromisoformat(checked))
            except ValueError:
                when = "recently"
            self._line.value = f"{__version__} · up to date (checked {when})"
            self._line.color = Palette.ON_SURFACE
        else:
            self._line.value, self._line.color = __version__, Palette.ON_SURFACE
        self._download.visible = newer
        if is_mounted(self):
            self.update()

    def check_now(self) -> None:
        def done(release) -> None:
            self.refresh()
            if release is not None:
                self.ctx.toast(f"Version {release.version} is available", "info", action="Download",
                               on_action=lambda: open_url(self.ctx.page, release.url))
            else:
                self.ctx.toast("No newer version found (or GitHub couldn't be reached; see the log)", "info")

        self.ctx.run_in_background(self.store.check_updates_now, on_done=done,
                                   on_error=lambda exc: self.ctx.toast(f"Couldn't check for updates: {exc}", "error"),
                                   busy=[self._check], spinner=self._spinner)

    def _open(self) -> None:
        open_url(self.ctx.page, self._release.url if self._release else update_check.RELEASES_PAGE)


__all__ = ["UpdateRow"]
