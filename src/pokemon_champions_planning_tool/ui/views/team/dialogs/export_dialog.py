"""Export dialog: Showdown text with copy, and publish to Poképast.es."""

from __future__ import annotations

import flet as ft

from ....components.banner import InlineBanner
from ....context import AppContext
from ....tasks import is_mounted
from ....theme import Palette, Space
from ..store import TeamStore


class ExportDialog(ft.AlertDialog):
    def __init__(self, ctx: AppContext, store: TeamStore) -> None:
        super().__init__(modal=True, scrollable=True)
        self.ctx = ctx
        self.store = store
        text = store.export_text().strip() or "(No team members to export)"
        self._text = ft.TextField(value=text, multiline=True, min_lines=8, max_lines=16, read_only=True,
                                  text_style=ft.TextStyle(font_family="monospace", size=12))
        self._banner = InlineBanner(visible=False)
        self._link = ft.TextButton("Open paste", icon=ft.Icons.OPEN_IN_NEW, visible=False)
        self._copy_link = ft.TextButton("Copy link", icon=ft.Icons.LINK, visible=False)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._publish = ft.FilledButton("Publish to Poképast.es", icon=ft.Icons.UPLOAD, on_click=lambda _e: self._do_publish())
        self.url: str | None = None

        self.title = ft.Text(f"Export · {store.active_team_name}")
        self.content = ft.Container(width=640, content=ft.Column(spacing=Space.MD, tight=True, controls=[self._text, self._banner, ft.Row(spacing=Space.SM, controls=[self._link, self._copy_link])]))
        self.actions = [
            ft.TextButton("Close", on_click=lambda _e: self.close()),
            ft.FilledTonalButton("Copy", icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._copy()),
            self._spinner,
            self._publish,
        ]
        self.actions_alignment = ft.MainAxisAlignment.END

    def close(self) -> None:
        page = getattr(self.ctx, "page", None)
        if page is not None:
            if hasattr(page, "_dialogs") and hasattr(page._dialogs, "controls"):
                if self.open and self in page._dialogs.controls:
                    for _ in range(len(page._dialogs.controls) + 1):
                        popped = page.pop_dialog()
                        if popped is self or popped is None or not self.open:
                            break
            elif hasattr(page, "dialogs"):
                if self in page.dialogs or self.open:
                    while page.dialogs:
                        popped = page.pop_dialog()
                        if popped is self or popped is None:
                            break
            elif hasattr(page, "pop_dialog"):
                page.pop_dialog()
        self.open = False
        if is_mounted(self):
            try:
                self.update()
            except Exception:
                pass

    def _copy(self) -> None:
        self.ctx.copy_to_clipboard(self._text.value or "")
        self.ctx.toast("Showdown text copied", "success")

    def _do_publish(self) -> None:
        self._banner.hide()

        def done(result) -> None:
            self.url = result.pokepast_url
            self._banner.show(f"Published: {result.pokepast_url}", "success")
            self._link.visible = bool(result.pokepast_url)
            self._link.on_click = lambda _e: self.ctx.page.launch_url(result.pokepast_url)
            self._copy_link.visible = bool(result.pokepast_url)
            self._copy_link.on_click = lambda _e: (self.ctx.copy_to_clipboard(result.pokepast_url), self.ctx.toast("Link copied", "success"))
            self._publish.content = "Published"
            self._publish.disabled = True
            if is_mounted(self):
                self.update()

        def failed(exc: BaseException) -> None:
            self._banner.show(f"Publish failed: {exc}", "error")
            if is_mounted(self):
                self.update()

        self.ctx.run_in_background(self.store.publish, on_done=done, on_error=failed, busy=[self._publish], spinner=self._spinner)


__all__ = ["ExportDialog", "Palette"]
