"""Settings page: data-source syncs and app information."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import flet as ft

from ....config import DEFAULT_CSV_FILENAME, DEFAULT_DATABASE_FILENAME
from ... import events
from ...components import KeyValueList, PageHeader, Panel, SectionHeader
from ...context import AppContext
from ...format import absolute_time, plural, relative_time
from ...theme import IconSize, Palette, Radius, Space
from .store import SettingsStatus, SettingsStore

_MAX_WIDTH = 720


class SyncRow(ft.Container):
    """One data source: icon, title, status caption, Sync button, progress bar."""

    def __init__(self, icon: str, title: str, on_sync: Callable[[], None]) -> None:
        super().__init__()
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._result = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.SUCCESS, visible=False)
        self.spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self.button = ft.FilledTonalButton("Sync", icon=ft.Icons.SYNC, on_click=lambda _e: on_sync())
        self._bar = ft.ProgressBar(visible=False, bar_height=2, color=Palette.PRIMARY, bgcolor=Palette.OUTLINE_VARIANT)

        self.content = ft.Column(
            spacing=Space.SM,
            tight=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Row(
                            spacing=Space.MD,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Container(
                                    content=ft.Icon(icon, size=IconSize.LG, color=Palette.ON_SURFACE_VARIANT),
                                    width=40,
                                    height=40,
                                    alignment=ft.Alignment.CENTER,
                                    bgcolor=Palette.SURFACE_3,
                                    border_radius=Radius.PILL,
                                ),
                                ft.Column(
                                    spacing=2,
                                    tight=True,
                                    controls=[
                                        ft.Text(title, theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE),
                                        ft.Row(spacing=Space.SM, controls=[self._status, self._result]),
                                    ],
                                ),
                            ],
                        ),
                        ft.Row(spacing=Space.SM, controls=[self.spinner, self.button]),
                    ],
                ),
                self._bar,
            ],
        )
        self.padding = ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM)
        self.border_radius = Radius.MD

    def set_status(self, text: str) -> None:
        self._status.value = text

    def set_result(self, text: str | None, *, error: bool = False) -> None:
        self._result.value = text or ""
        self._result.visible = bool(text)
        self._result.color = Palette.ERROR if error else Palette.SUCCESS

    def set_running(self, running: bool) -> None:
        self._bar.visible = running
        if running:
            self.set_result(None)


class SettingsView(ft.Column):
    def __init__(self, ctx: AppContext, store: SettingsStore | None = None) -> None:
        super().__init__(spacing=Space.LG, expand=True, scroll=ft.ScrollMode.AUTO)
        self.ctx = ctx
        self.store = store or SettingsStore()

        self.header = PageHeader("Settings")
        self.row_megas = SyncRow(ft.Icons.BOLT, "Mega Evolutions", lambda: self._sync("megas"))
        self.row_items = SyncRow(ft.Icons.DIAMOND_OUTLINED, "Held items", lambda: self._sync("items"))
        self.row_tournaments = SyncRow(ft.Icons.EMOJI_EVENTS_OUTLINED, "Tournaments", lambda: self._sync("tournaments"))
        self._rows = {"megas": self.row_megas, "items": self.row_items, "tournaments": self.row_tournaments}

        self.about = KeyValueList(self._about_rows())

        self.controls = [
            self.header,
            ft.Container(
                width=_MAX_WIDTH,
                content=ft.Column(
                    spacing=Space.LG,
                    controls=[
                        Panel(
                            [
                                SectionHeader("Data sources"),
                                ft.Text(
                                    "The local catalogue is built from PokéAPI, Pokémon Showdown, Limitless and "
                                    "Victory Road. Tournaments also sync in the background on startup.",
                                    theme_style=ft.TextThemeStyle.BODY_SMALL,
                                    color=Palette.ON_SURFACE_VARIANT,
                                ),
                                self.row_megas,
                                ft.Divider(),
                                self.row_items,
                                ft.Divider(),
                                self.row_tournaments,
                            ]
                        ),
                        Panel([SectionHeader("About"), self.about]),
                    ],
                ),
            ),
        ]

        ctx.bus.on(events.META_SYNCED, lambda _payload: self.refresh())

    # -- lifecycle ----------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the counts. Called on activation and after any sync."""
        status = self.store.status()
        self.apply_status(status)
        if self._is_mounted():
            self.update()

    def apply_status(self, status: SettingsStatus) -> None:
        self.row_megas.set_status(_status_line(plural(status.mega_count, "form"), status.megas_checked_at, status.mega_count))
        self.row_items.set_status(_status_line(plural(status.item_count, "item"), status.items_synced_at, status.item_count))
        self.row_tournaments.set_status(
            _status_line(
                f"{plural(status.tournament_count, 'event')} · {plural(status.tournament_team_count, 'team')}",
                status.tournaments_synced_at,
                status.tournament_count,
            )
        )

    # -- syncing ------------------------------------------------------------------------

    def _sync(self, kind: str) -> None:
        row = self._rows[kind]
        work = {"megas": self.store.sync_megas, "items": self.store.sync_items, "tournaments": self.store.sync_tournaments}[kind]
        row.set_running(True)
        row.set_status("Syncing…")
        if self._is_mounted():
            row.update()

        def done(result: dict[str, Any]) -> None:
            row.set_running(False)
            row.set_result(_result_summary(kind, result))
            self.refresh()
            self.ctx.toast(_toast_text(kind, result), "success")
            self.ctx.bus.emit(events.CATALOGS_RELOADED, kind)

        def failed(exc: BaseException) -> None:
            row.set_running(False)
            row.set_result("Sync failed", error=True)
            self.refresh()
            self.ctx.toast(f"{kind.capitalize()} sync failed: {exc}", "error")

        self.ctx.run_in_background(work, on_done=done, on_error=failed, busy=[row.button], spinner=row.spinner)

    # -- helpers ------------------------------------------------------------------------

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _about_rows() -> list[tuple[str, str | ft.Control]]:
        try:
            from importlib.metadata import version

            app_version = version("pokemon-champions-planning-tool")
        except Exception:  # noqa: BLE001 - not installed as a distribution
            app_version = "dev"
        sources = ft.Row(
            wrap=True,
            spacing=Space.SM,
            controls=[
                ft.TextButton("PokéAPI", url="https://pokeapi.co"),
                ft.TextButton("Pokémon Showdown", url="https://play.pokemonshowdown.com"),
                ft.TextButton("Limitless", url="https://play.limitlesstcg.com"),
                ft.TextButton("Victory Road", url="https://victoryroad.pro"),
            ],
        )
        return [
            ("Version", app_version),
            ("Database", str(Path(DEFAULT_DATABASE_FILENAME).resolve())),
            ("CSV export", str(Path(DEFAULT_CSV_FILENAME).resolve())),
            ("Data sources", sources),
        ]


def _status_line(counts: str, synced_at, count: int) -> str:
    if count == 0:
        return "Never synced"
    return f"{counts} · synced {relative_time(synced_at)}"


def _result_summary(kind: str, result: dict[str, Any]) -> str:
    if kind == "megas":
        return f"+{result.get('added', 0)} forms"
    if kind == "items":
        return f"+{result.get('added', 0)} added · {result.get('updated', 0)} updated"
    limitless = result.get("limitless", {})
    victory = result.get("victory_road", {})
    added = int(limitless.get("added", 0)) + int(victory.get("added", 0))
    backlog = limitless.get("backlog_remaining")
    tail = f" · {backlog:,} pending" if backlog else ""
    return f"+{added} teams{tail}"


def _toast_text(kind: str, result: dict[str, Any]) -> str:
    if kind == "megas":
        return f"Mega Evolutions synced — {result.get('total_local', 0):,} forms cached"
    if kind == "items":
        return f"Items synced — {result.get('total', 0):,} catalogued"
    status = result.get("status", "synced")
    if status == "offline":
        return "Tournament sources unreachable — kept existing data"
    return "Tournament data synced from Limitless and Victory Road"


__all__ = ["SettingsView", "SyncRow", "absolute_time"]
