"""Settings page: data-source syncs and app information."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import flet as ft

from ....config import DEFAULT_CSV_FILENAME, DEFAULT_DATABASE_FILENAME, DISCLAIMER
from ... import events
from ...components import KeyValueList, PageHeader, Panel, SectionHeader
from ...context import AppContext
from ...format import absolute_time, plural, relative_time
from ...theme import Accent, IconSize, Palette, Radius, Space
from .format_panel import FormatDialog, FormatPanel
from .store import SettingsStatus, SettingsStore

_MAX_WIDTH = 720


class SyncRow(ft.Container):
    """One data source: icon, title, status caption, Sync button, progress bar."""

    def __init__(self, icon: str, title: str, on_sync: Callable[[], None], *, button_label: str = "Sync") -> None:
        super().__init__()
        self._status = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._result = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.SUCCESS, visible=False)
        self.spinner = ft.ProgressRing(width=16, height=16, stroke_width=2, visible=False)
        self.button = ft.FilledTonalButton(button_label, icon=ft.Icons.SYNC if button_label == "Sync" else ft.Icons.HEALING, on_click=lambda _e: on_sync())
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
        self._bar.value = None
        if running:
            self.set_result(None)

    def set_progress(self, progress) -> None:
        """Follow a SyncProgress snapshot: status text and a determinate bar."""
        self._bar.visible = progress.running
        self._bar.value = progress.fraction
        text = progress.message
        if progress.running and progress.teams_added:
            text += f" · {progress.teams_added:,} teams"
        self._status.value = text
        if progress.running:
            self.set_result(None)


class SettingsView(ft.Column):
    def __init__(self, ctx: AppContext, store: SettingsStore | None = None) -> None:
        super().__init__(spacing=Space.LG, expand=True, scroll=ft.ScrollMode.AUTO)
        self.ctx = ctx
        self.store = store or SettingsStore()

        self.header = PageHeader("Settings", icon=ft.Icons.SETTINGS, accent=Accent.SETTINGS)
        self.row_megas = SyncRow(ft.Icons.BOLT, "Mega Evolutions", lambda: self._sync("megas"))
        self.row_items = SyncRow(ft.Icons.DIAMOND_OUTLINED, "Held items", lambda: self._sync("items"))
        self.row_moves = SyncRow(ft.Icons.SPORTS_MARTIAL_ARTS, "Moves, learnsets & species", lambda: self._sync("moves"))
        self.row_tournaments = SyncRow(ft.Icons.EMOJI_EVENTS_OUTLINED, "Tournaments", lambda: self._sync("tournaments"))
        self.row_sprites = SyncRow(ft.Icons.IMAGE_OUTLINED, "Local sprite cache", lambda: self._sync("sprites"), button_label="Pre-cache")
        self.row_health = SyncRow(ft.Icons.HEALTH_AND_SAFETY_OUTLINED, "Data health", lambda: self._sync("health"), button_label="Repair")
        self._rows = {"megas": self.row_megas, "items": self.row_items, "moves": self.row_moves, "tournaments": self.row_tournaments, "sprites": self.row_sprites, "health": self.row_health}

        self.about = KeyValueList(self._about_rows())

        self.formats = FormatPanel(registry=ctx.formats, on_edit=self._edit_format, on_delete=self._delete_format, on_default=self._set_default_format)
        self._format_dropdown = ft.Dropdown(
            label="Tournament filter",
            value=self.store.get_battle_format_preference(),
            options=[
                ft.DropdownOption(key="doubles", text="Doubles only (VGC default)"),
                ft.DropdownOption(key="all", text="All formats (Doubles & Singles)"),
                ft.DropdownOption(key="singles", text="Singles only"),
            ],
            width=320,
            on_select=lambda e: self._on_format_changed(e.control.value or "doubles"),
        )

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
                                self.row_moves,
                                ft.Divider(),
                                self.row_tournaments,
                                ft.Divider(),
                                self.row_sprites,
                                ft.Divider(),
                                self.row_health,
                            ]
                        ),
                        self.formats,
                        Panel(
                            [
                                SectionHeader("Tournament preferences"),
                                ft.Text(
                                    "Official Play! Pokémon events and standard VGC are Doubles. "
                                    "When set to Doubles only, community Singles/3v3 tournaments are excluded "
                                    "from Meta Explorer, partner synergies, and damage calculator build presets.",
                                    theme_style=ft.TextThemeStyle.BODY_SMALL,
                                    color=Palette.ON_SURFACE_VARIANT,
                                ),
                                ft.Row(
                                    spacing=Space.MD,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                    controls=[
                                        ft.Icon(ft.Icons.TUNE, size=IconSize.LG, color=Palette.ON_SURFACE_VARIANT),
                                        self._format_dropdown,
                                    ],
                                ),
                            ]
                        ),
                        Panel([SectionHeader("About"), self.about]),
                    ],
                ),
            ),
        ]

        ctx.bus.on(events.META_SYNCED, lambda _payload: self.refresh())
        ctx.bus.on(events.FORMAT_CHANGED, lambda _payload: self.formats.render())
        ctx.bus.on(events.SYNC_PROGRESS, lambda p: self._on_sync_progress(p))

    # -- lifecycle ----------------------------------------------------------------------

    def refresh(self) -> None:
        """Reload the counts. Called on activation and after any sync."""
        def on_done(status: SettingsStatus) -> None:
            self.apply_status(status)
            if self._is_mounted():
                self.update()

        if self._is_mounted() and hasattr(self.ctx, "run_in_background"):
            self.ctx.run_in_background(self.store.status, on_done=on_done, on_error=lambda _e: None)
        else:
            status = self.store.status()
            self.apply_status(status)
            if self._is_mounted():
                self.update()

    def apply_status(self, status: SettingsStatus) -> None:
        self.row_megas.set_status(_status_line(plural(status.mega_count, "form"), status.megas_checked_at, status.mega_count))
        self.row_items.set_status(_status_line(plural(status.item_count, "item"), status.items_synced_at, status.item_count))
        self.row_moves.set_status(_status_line(f"{plural(status.move_count, 'move')} · {plural(status.move_species_count, 'learnset')}", status.moves_synced_at, status.move_count))
        if status.placeholder_in_box:
            self.row_health.set_status(f"{plural(status.placeholder_in_box, 'Pokémon')} in the box without PokéAPI data · {plural(status.placeholder_records, 'placeholder record')}")
        else:
            self.row_health.set_status("All box Pokémon have complete data" + (f" · {plural(status.placeholder_records, 'unused placeholder record')}" if status.placeholder_records else ""))
        self.row_health.button.disabled = status.placeholder_in_box == 0
        self.row_tournaments.set_status(
            _status_line(
                f"{plural(status.tournament_count, 'event')} · {plural(status.tournament_team_count, 'team')}",
                status.tournaments_synced_at,
                status.tournament_count,
            )
        )
        if status.cached_sprites > 0:
            size_kb = round(status.cached_sprites_bytes / 1024)
            self.row_sprites.set_status(f"{plural(status.cached_sprites, 'sprite')} cached locally ({size_kb:,} KB) · shown offline")
        else:
            self.row_sprites.set_status("No sprites cached yet (loading on-demand from Showdown CDN)")
        self._format_dropdown.value = self.store.get_battle_format_preference()

    def _on_format_changed(self, val: str) -> None:
        self.store.set_battle_format_preference(val)
        self.ctx.bus.emit(events.BATTLE_FORMAT_CHANGED, val)
        labels = {"doubles": "Doubles only", "all": "All formats", "singles": "Singles only"}
        self.ctx.toast(f"Tournament filter set to {labels.get(val, val)}", "success")

    # -- formats --------------------------------------------------------------------------

    def _set_default_format(self, format_id: str) -> None:
        registry = self.ctx.formats
        if format_id and format_id != registry.default().format_id:
            registry.set_default(format_id)
            self.ctx.toast(f"Default format: {registry.default().name}", "success")

    def _edit_format(self, fmt) -> None:
        page = self.ctx.page

        def saved(new) -> None:
            page.pop_dialog()
            self.ctx.toast(f"Saved format “{new.name}”", "success")

        page.show_dialog(FormatDialog(registry=self.ctx.formats, fmt=fmt, on_saved=saved, on_close=page.pop_dialog))

    def _delete_format(self, fmt) -> None:
        registry = self.ctx.formats
        registry.delete_custom(fmt.format_id)
        self.ctx.toast(f"Deleted format “{fmt.name}”; its teams follow the default", "info", action="Undo",
                       on_action=lambda: registry.save_custom(fmt))

    # -- syncing ------------------------------------------------------------------------

    def _sync(self, kind: str) -> None:
        row = self._rows[kind]
        work = {
            "megas": self.store.sync_megas,
            "items": self.store.sync_items,
            "moves": self.store.sync_moves,
            "tournaments": self.store.sync_tournaments,
            "sprites": self.store.sync_sprites,
            "health": self.store.repair_data,
        }[kind]
        row.set_running(True)
        row.set_status("Syncing…")
        if self._is_mounted():
            row.update()

        def done(result: dict[str, Any]) -> None:
            row.set_running(False)
            row.set_result(_result_summary(kind, result))
            self.refresh()
            self.ctx.toast(_toast_text(kind, result), "success")
            self.ctx.bus.emit(events.BOX_CHANGED if kind == "health" else events.CATALOGS_RELOADED, None if kind == "health" else kind)

        def failed(exc: BaseException) -> None:
            row.set_running(False)
            row.set_result("Sync failed", error=True)
            self.refresh()
            self.ctx.toast(f"{kind.capitalize()} sync failed: {exc}", "error")

        if kind == "tournaments":
            from ....services.tournament_sync_service import sync_in_progress

            if sync_in_progress():
                row.set_running(False)
                row.set_status("A sync is already running")
                self.ctx.toast("A sync is already running", "info")
                return
            self.ctx.sync_tournaments(work, on_done=done, on_error=failed, busy=[row.button], spinner=row.spinner)
            return
        self.ctx.run_in_background(work, on_done=done, on_error=failed, busy=[row.button], spinner=row.spinner)

    def _on_sync_progress(self, progress) -> None:
        row = self.row_tournaments
        row.set_progress(progress)
        row.button.disabled = progress.running
        if self._is_mounted():
            row.update()

    # -- helpers ------------------------------------------------------------------------

    def _is_mounted(self) -> bool:
        try:
            return self.page is not None
        except RuntimeError:
            return False

    @staticmethod
    def _about_rows() -> list[tuple[str, str | ft.Control]]:
        from pokemon_champions_planning_tool import __version__ as app_version
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
            ("License", ft.TextButton("MIT · third-party notices", url="https://github.com/JsNcAr/champions-metadesk-studio/blob/main/NOTICE.md")),
            ("Disclaimer", ft.Text(DISCLAIMER, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)),
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
    if kind == "moves":
        return f"{result.get('moves', 0):,} moves · {result.get('species', 0):,} learnsets · {result.get('species_catalog', 0):,} species"
    if kind == "health":
        return f"{result.get('repaired', 0)} of {result.get('stubs', 0)} repaired"
    if kind == "sprites":
        return f"{result.get('enqueued', 0)} queued · {result.get('cached', 0)} cached"
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
    if kind == "sprites":
        return f"Pre-caching {result.get('enqueued', 0)} sprites in the background"
    if kind == "health":
        stubs, repaired = result.get("stubs", 0), result.get("repaired", 0)
        return "Nothing to repair" if not stubs else (f"Repaired {repaired} Pokémon" if repaired == stubs else f"Repaired {repaired} of {stubs} — PokéAPI unreachable for the rest")
    if kind == "moves":
        return "Move catalogue unreachable — kept existing data" if result.get("status") == "offline" else f"Moves synced — {result.get('moves', 0):,} moves, {result.get('species', 0):,} Champions learnsets"
    status = result.get("status", "synced")
    if status == "offline":
        return "Tournament sources unreachable — kept existing data"
    return "Tournament data synced from Limitless and Victory Road"


__all__ = ["SettingsView", "SyncRow", "absolute_time"]
