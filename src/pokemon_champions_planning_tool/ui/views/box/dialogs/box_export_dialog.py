"""Export dialog: Box roster export in JSON backup, plain text, or CSV."""

from __future__ import annotations

from typing import TYPE_CHECKING

import flet as ft

from ....components.banner import InlineBanner
from ....tasks import is_mounted
from ....theme import Palette, Space

if TYPE_CHECKING:
    from .....domain.entities.box_entry import BoxEntry
    from ....context import AppContext
    from ..store import BoxStore

_FILENAMES = {
    "json": "champions_box.json",
    "text": "champions_box.txt",
    "csv": "champions_box.csv",
}


class BoxExportDialog(ft.AlertDialog):
    def __init__(
        self,
        ctx: AppContext,
        store: BoxStore,
        *,
        entries: list[BoxEntry] | None = None,
        title_suffix: str = "",
    ) -> None:
        super().__init__(modal=True, scrollable=True)
        self.ctx = ctx
        self.store = store
        self.entries = entries if entries is not None else store.entries
        self.current_format = "json"

        count = len(self.entries)
        title_text = f"Export Box · {count} Pokémon{title_suffix}"
        self.title = ft.Text(title_text)

        # Segmented format selector
        self._format_picker = ft.SegmentedButton(
            selected={self.current_format},
            allow_multiple_selection=False,
            segments=[
                ft.Segment(value="json", label=ft.Text("JSON Backup"), tooltip="Full fidelity: includes tags, notes, favorites, forms"),
                ft.Segment(value="text", label=ft.Text("Names List"), tooltip="Plain text list of species names"),
                ft.Segment(value="csv", label=ft.Text("CSV"), tooltip="Spreadsheet format with metadata and stats"),
            ],
            on_change=lambda e: self._on_format_changed(list(e.control.selected)[0] if e.control.selected else "json"),
        )

        self._text = ft.TextField(
            value="",
            multiline=True,
            min_lines=10,
            max_lines=16,
            read_only=True,
            text_style=ft.TextStyle(font_family="monospace", size=12),
        )
        self._banner = InlineBanner(visible=False)

        self.content = ft.Container(
            width=680,
            content=ft.Column(
                spacing=Space.MD,
                tight=True,
                controls=[
                    ft.Row(alignment=ft.MainAxisAlignment.CENTER, controls=[self._format_picker]),
                    self._text,
                    self._banner,
                ],
            ),
        )

        self.actions = [
            ft.TextButton("Close", on_click=lambda _e: self.close()),
            ft.FilledTonalButton("Save File", icon=ft.Icons.SAVE_ALT, on_click=lambda _e: self._save_file()),
            ft.FilledButton("Copy to Clipboard", icon=ft.Icons.CONTENT_COPY, on_click=lambda _e: self._copy()),
        ]
        self.actions_alignment = ft.MainAxisAlignment.END

        self._update_text()

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

    def _on_format_changed(self, new_format: str) -> None:
        self.current_format = new_format
        self._banner.hide()
        self._update_text()
        if is_mounted(self):
            self.update()

    def _update_text(self) -> None:
        try:
            self._text.value = self.store.export_box(self.current_format, entries=self.entries)
        except Exception as exc:
            self._text.value = f"Error generating export: {exc}"

    def _copy(self) -> None:
        self.ctx.copy_to_clipboard(self._text.value or "")
        format_label = {"json": "JSON backup", "text": "Names list", "csv": "CSV data"}.get(self.current_format, "Data")
        self.ctx.toast(f"{format_label} copied to clipboard", "success")

    def _save_file(self) -> None:
        filename = _FILENAMES.get(self.current_format, "box_export.txt")
        try:
            path = self.store.save_export_file(self._text.value or "", filename)
            self._banner.show(f"Saved to {path.name} in project directory", "success")
            self.ctx.toast(f"Saved {path.name}", "success")
        except Exception as exc:
            self._banner.show(f"Error saving file: {exc}", "error")
        if is_mounted(self):
            self.update()
