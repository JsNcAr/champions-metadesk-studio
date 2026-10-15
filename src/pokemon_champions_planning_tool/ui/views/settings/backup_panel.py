"""Settings › Backup & restore: one zip of everything, and restoring one at the next launch.

A restore is never applied while the app runs (views, sync threads and delayed saves all
hold the database): the backup is checked and staged now, and ``main.run`` applies it the
next time the app starts, after backing up the data it replaces.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import flet as ft

from .... import storage
from ...components import Panel, SectionHeader
from ...context import AppContext
from ...tasks import is_mounted, reveal
from ...theme import Palette, Space


def _when(dt: datetime | None, path: Path) -> str:
    stamp = dt or datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    return f"{stamp.astimezone():%d %b %Y, %H:%M}"


def _size(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB" if n >= 100_000 else f"{max(1, n // 1000)} KB"


def _small(text: str, *, color: str = Palette.ON_SURFACE_VARIANT) -> ft.Text:
    return ft.Text(text, theme_style=ft.TextThemeStyle.BODY_SMALL, color=color)


class BackupPanel(Panel):
    def __init__(self, ctx: AppContext) -> None:
        spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        backup = ft.FilledTonalButton("Back up now", icon=ft.Icons.SAVE_ALT, on_click=lambda _e: self.back_up())
        restore = ft.OutlinedButton("Restore…", icon=ft.Icons.RESTORE, on_click=lambda _e: self.open_restore())
        pending = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True)
        auto = storage.auto_backup_folder()
        super().__init__([
            SectionHeader("Backup & restore"),
            _small("A backup is one zip with your box, teams, plans, rival presets, formats and settings "
                   "(and the tournament data, so a restore needs no resync). Restoring replaces all of it, "
                   "after saving what it replaces."),
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[backup, restore, spinner]),
            pending,
            ft.Row(spacing=Space.XS, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                _small(f"Automatic backups before a restore or an upgrade: {auto}"),
                ft.TextButton("Open", icon=ft.Icons.FOLDER_OPEN_OUTLINED, data={"open": str(auto)}, on_click=lambda _e: self._open(auto)),
            ]),
        ])
        self.ctx = ctx
        self._spinner, self._backup, self._restore, self._pending = spinner, backup, restore, pending
        self.render_pending()

    # -- backing up -----------------------------------------------------------------------

    def back_up(self) -> None:
        self.ctx.run_shutdown_hooks()   # delayed saves (the calc state) reach preferences.json first

        def done(path: Path) -> None:
            self.ctx.toast(f"Backup saved to {path}", "success", action="Open folder", on_action=lambda: self._open(path.parent))

        def failed(exc: BaseException) -> None:
            self.ctx.toast(f"Couldn't back up: {exc}", "error")

        self.ctx.run_in_background(storage.create_backup, on_done=done, on_error=failed,
                                   busy=[self._backup, self._restore], spinner=self._spinner)

    # -- restoring ------------------------------------------------------------------------

    def open_restore(self) -> None:
        page = self.ctx.page

        def staged(info: storage.BackupInfo) -> None:
            self.render_pending()

        dialog = RestoreDialog(self.ctx, backups=storage.list_backups(), on_staged=staged, on_close=page.pop_dialog)
        page.show_dialog(dialog)

    def render_pending(self) -> None:
        meta = storage.pending_restore()
        if meta is None:
            self._pending.controls, self._pending.visible = [], False
        else:
            self._pending.visible = True
            self._pending.controls = [
                ft.Icon(ft.Icons.SCHEDULE, size=16, color=Palette.WARNING),
                _small("A restore is waiting: it finishes the next time the app starts.", color=Palette.WARNING),
                ft.TextButton("Cancel it", on_click=lambda _e: self._cancel_pending()),
            ]
        if is_mounted(self):
            self.update()

    def _cancel_pending(self) -> None:
        storage.cancel_pending_restore()
        self.render_pending()
        self.ctx.toast("The waiting restore was cancelled; your data stays as it is", "info")

    def _open(self, folder: Path) -> None:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            reveal(folder)
        except OSError as exc:
            self.ctx.toast(f"Couldn't open the folder: {exc}. It is {folder}", "warning")


class RestoreDialog(ft.AlertDialog):
    """Pick a backup (found ones, or a pasted path), check it, confirm, stage it.

    Three steps in one dialog rather than dialogs on top of each other: choose, then
    "Replace my data" once the backup is checked, then "Restore ready"."""

    def __init__(self, ctx: AppContext, *, backups: list[Path], on_staged: Callable[[storage.BackupInfo], None],
                 on_close: Callable[[], None]) -> None:
        super().__init__(modal=True, scrollable=True)
        self.ctx = ctx
        self._on_staged = on_staged
        self._on_close = on_close
        self._checked: storage.BackupInfo | None = None
        self.title = ft.Text("Restore a backup")
        self._choices = ft.RadioGroup(
            value=str(backups[0]) if backups else None,
            on_change=lambda _e: self._reset(),
            content=ft.Column(spacing=0, tight=True, controls=[
                ft.Radio(value=str(p), label=f"{_when(None, p)} · {p.parent.name} · {_size(p.stat().st_size)}", data={"backup": str(p)})
                for p in backups
            ]),
        )
        self._path = ft.TextField(label="…or paste the path to a backup file", dense=True, on_change=lambda _e: self._reset())
        self._details = _small("")
        self._details.visible = False
        self._error = _small("", color=Palette.ERROR)
        self._error.visible = False
        self._spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        found = ([_small("Backups found in your Downloads and the app's backup folder:"), self._choices] if backups
                 else [_small("No backups found in your Downloads or the app's backup folder.")])
        self.content = ft.Container(width=480, content=ft.Column(spacing=Space.MD, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                                                                 controls=[*found, self._path, self._details, self._error]))
        self._next = ft.FilledButton("Check backup", icon=ft.Icons.FACT_CHECK_OUTLINED, on_click=lambda _e: self._advance())
        self.actions = [self._spinner, ft.TextButton("Cancel", on_click=lambda _e: on_close()), self._next]
        self.actions_alignment = ft.MainAxisAlignment.END

    def selected(self) -> str:
        return (self._path.value or "").strip() or (self._choices.value or "")

    def _reset(self) -> None:
        """A different backup was picked: check it again before anything is replaced."""
        if self._checked is None and not self._error.visible:
            return
        self._checked = None
        self._details.visible = self._error.visible = False
        self._next.content, self._next.icon = "Check backup", ft.Icons.FACT_CHECK_OUTLINED
        self._refresh()

    def _advance(self) -> None:
        path = self.selected()
        if not path:
            self._show_error("Pick a backup, or paste the path to one")
            return
        if self._checked is None:
            self._run(lambda: storage.inspect_backup(path), self._show_checked)
        else:
            self._run(lambda: storage.stage_restore(path), self._show_staged)

    def _run(self, work, on_done) -> None:
        self._error.visible = False

        def failed(exc: BaseException) -> None:
            self._show_error(str(exc) if isinstance(exc, storage.BackupError) else f"Couldn't read the backup: {exc}")

        self.ctx.run_in_background(work, on_done=on_done, on_error=failed, busy=[self._next], spinner=self._spinner)

    def _show_checked(self, info: storage.BackupInfo) -> None:
        self._checked = info
        prefs = "with your settings" if info.has_preferences else "without settings"
        self._details.value = (f"Made {_when(info.created_at, info.path)} by version {info.version}, {_size(info.size)}, {prefs}.\n"
                               "Restoring replaces your box, teams, plans, presets, formats and settings with this backup's. "
                               "Your current data is backed up first.")
        self._details.color = Palette.ON_SURFACE
        self._details.visible = True
        self._next.content, self._next.icon = "Replace my data", ft.Icons.RESTORE
        self._refresh()

    def _show_staged(self, info: storage.BackupInfo) -> None:
        self._on_staged(info)
        self.title = ft.Text("Restore ready")
        self.content = ft.Container(width=480, content=ft.Column(spacing=Space.MD, tight=True, controls=[
            ft.Text("The backup is checked and waiting. It replaces your data the next time the app starts, "
                    "before anything else opens it; your current data is backed up first.",
                    theme_style=ft.TextThemeStyle.BODY_MEDIUM),
            _small("Until then, changes you make are saved as usual, then replaced by the backup."),
        ]))
        actions: list[ft.Control] = [ft.TextButton("Later", on_click=lambda _e: self._on_close())]
        if not getattr(self.ctx.page, "web", False):   # a browser tab can't close the server
            actions.append(ft.FilledButton("Close the app now", icon=ft.Icons.POWER_SETTINGS_NEW, on_click=lambda _e: self._quit()))
        self.actions = actions
        self._refresh()

    def _quit(self) -> None:
        self.ctx.run_shutdown_hooks()
        self.ctx.page.run_task(self.ctx.page.window.close)

    def _show_error(self, message: str) -> None:
        self._error.value, self._error.visible = message, True
        self._refresh()

    def _refresh(self) -> None:
        if is_mounted(self):
            self.update()


__all__ = ["BackupPanel", "RestoreDialog"]
