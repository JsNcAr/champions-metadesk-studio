"""Import dialog: Box roster import from JSON backup, plain text list, or CSV."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import flet as ft

from .....services.box_transfer_service import BoxImportReport, ParsedBoxResult, parse_box_import_text
from .... import events
from ....components.banner import InlineBanner
from ....tasks import is_mounted
from ....theme import Palette, Space

if TYPE_CHECKING:
    from ....context import AppContext
    from ..store import BoxStore


class BoxImportDialog(ft.AlertDialog):
    def __init__(
        self,
        ctx: AppContext,
        store: BoxStore,
        *,
        initial_text: str = "",
        on_done: Callable[[BoxImportReport], None] | None = None,
    ) -> None:
        super().__init__(modal=True, scrollable=True)
        self.ctx = ctx
        self.store = store
        self._on_done = on_done
        self.parsed: ParsedBoxResult = parse_box_import_text(initial_text)

        self.title = ft.Text("Import Box")

        self._input = ft.TextField(
            hint_text="Paste JSON backup or species names (e.g. Charizard\nIncineroar #VGC ★\nRillaboom...)",
            multiline=True,
            min_lines=8,
            max_lines=14,
            value=initial_text,
            text_style=ft.TextStyle(font_family="monospace", size=12),
            on_change=lambda _e: self._on_input_changed(),
        )

        self._status_text = ft.Text(
            "Paste or type Pokémon entries above",
            theme_style=ft.TextThemeStyle.BODY_SMALL,
            color=Palette.ON_SURFACE_VARIANT,
        )

        # Strategy picker: Merge (default) vs Replace
        self._strategy_radio = ft.RadioGroup(
            content=ft.Row(
                spacing=Space.MD,
                controls=[
                    ft.Radio(value="merge", label="Merge (Keep existing)"),
                    ft.Radio(value="replace", label="Replace entire box"),
                ],
            ),
            value="merge",
        )

        self._planned_checkbox = ft.Checkbox(
            label="Import as Planned (templates)",
            value=False,
            tooltip="Marks imported entries as planned/ghost entries (not yet owned)",
        )

        self._banner = InlineBanner(visible=False)
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self._import_button = ft.FilledButton(
            "Import",
            icon=ft.Icons.UPLOAD,
            disabled=True,
            on_click=lambda _e: self._do_import(),
        )

        self.content = ft.Container(
            width=680,
            content=ft.Column(
                spacing=Space.MD,
                tight=True,
                controls=[
                    self._input,
                    self._status_text,
                    ft.Text("Import strategy:", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT),
                    self._strategy_radio,
                    self._planned_checkbox,
                    self._banner,
                ],
            ),
        )

        self.actions = [
            ft.TextButton("Cancel", on_click=lambda _e: self.close()),
            self._spinner,
            self._import_button,
        ]
        self.actions_alignment = ft.MainAxisAlignment.END

        if initial_text:
            self._on_input_changed()

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

    def _on_input_changed(self) -> None:
        text = self._input.value or ""
        self.parsed = parse_box_import_text(text)
        count = len(self.parsed.items)

        if not text.strip():
            self._status_text.value = "Paste or type Pokémon entries above"
            self._status_text.color = Palette.ON_SURFACE_VARIANT
            self._import_button.disabled = True
            self._import_button.content = "Import"
        elif count == 0:
            self._status_text.value = "No valid Pokémon found in input"
            self._status_text.color = Palette.ERROR
            self._import_button.disabled = True
            self._import_button.content = "Import"
        else:
            format_names = {
                "json": "JSON Backup",
                "plain_text": "Plain Text List",
                "csv": "CSV Spreadsheet",
            }
            fmt_label = format_names.get(self.parsed.format_detected, self.parsed.format_detected.title())
            self._status_text.value = f"Detected {fmt_label} · {count} Pokémon"
            self._status_text.color = Palette.SUCCESS
            self._import_button.disabled = False
            self._import_button.content = f"Import ({count} Pokémon)"

        if is_mounted(self):
            self.update()

    def _do_import(self) -> None:
        if not self.parsed or not self.parsed.items:
            return

        strategy = self._strategy_radio.value or "merge"
        as_planned = True if self._planned_checkbox.value else None

        self._banner.hide()
        self._import_button.disabled = True
        self._spinner.visible = True
        if is_mounted(self):
            self.update()

        def background_work() -> BoxImportReport:
            return self.store.import_box(
                self.parsed.items,
                strategy=strategy,
                as_planned=as_planned,
            )

        def on_done(report: BoxImportReport) -> None:
            self._spinner.visible = False
            self._import_button.disabled = False
            self.close()

            # Emit notification to update all box views and teams
            self.ctx.bus.emit(events.BOX_CHANGED, None)

            # Show toast summary
            added_msg = f"Added {report.added}" if report.added else ""
            updated_msg = f"updated {report.updated}" if report.updated else ""
            parts = [p for p in (added_msg, updated_msg) if p]
            summary = ", ".join(parts) if parts else f"{report.total} Pokémon processed"
            self.ctx.toast(f"Import complete: {summary}", "success")

            if self._on_done:
                self._on_done(report)

        def on_error(exc: Exception) -> None:
            self._spinner.visible = False
            self._import_button.disabled = False
            self._banner.show(f"Import failed: {exc}", "error")
            if is_mounted(self):
                self.update()

        self.ctx.run_in_background(background_work, on_done=on_done, on_error=on_error)
