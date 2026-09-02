"""Help dialog: keyboard shortcuts and the features people would not find by themselves."""

from __future__ import annotations

import flet as ft

from ..config import DEFAULT_DATABASE_FILENAME, DEFAULT_PREFERENCES_FILENAME
from .components import SectionHeader
from .theme import Accent, Palette, Radius, Space

SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Ctrl+1 / 2 / 3", "Box · Teams · Meta"),
    ("Ctrl+,", "Settings"),
    ("F1 or Ctrl+/", "This help"),
    ("Ctrl+F", "Focus the search or filter field (Box, Meta)"),
    ("Ctrl+K", "Add a Pokémon to the box"),
    ("Ctrl+Shift+A", "Select every visible box entry"),
    ("Delete", "Delete the selected box entries (with Undo)"),
    ("Escape", "Close the dialog, then the side panel, then clear the selection"),
    ("Ctrl+N", "New team"),
    ("Ctrl+I", "Import a Showdown paste or Poképaste URL"),
    ("Ctrl+E", "Copy the active team as Showdown text"),
    ("Alt+← / →", "Move the focused slot card"),
)

TIPS: dict[str, tuple[str, ...]] = {
    "Box": (
        "Hover a card to reveal its checkbox; checking any card opens the bulk bar (favourite, tag, add to team, delete).",
        "Type · BST · Stats chips open a filter drawer; active filters appear as removable chips below the toolbar.",
        "Views ▾ saves the current filter set by name and applies it later; the View menu adds table columns and stats on cards.",
        "Export CSV writes the selection if there is one, otherwise the filtered entries.",
        "Deleting is reversible for a few seconds through the toast's Undo; only entries on a team ask first.",
    ),
    "Teams": (
        "Drag a slot card's header onto another card to swap them; the card menu offers the same and \"Move to lead\".",
        "The move picker lists only the species' Champions-legal moves, ranked by tournament usage. \"Show all moves\" in the team menu lists the rest with a warning.",
        "Mega forms use their base species' learnset; picking a Mega Stone switches the form automatically.",
        "Edit spread has EV/IV presets and refuses spreads over 510 EVs; the health chips explain each rule on hover.",
        "Compare teams… in the team menu shows two teams side by side, including uncovered types.",
        "Import from Meta opens the preview pre-filled; illegal species block the import, illegal moves only warn.",
    ),
    "Meta": (
        "Events show their winner only; \"Show N more\" or Expand all reveals the rest. The cards layout opens a full standings dialog per event.",
        "Official (Play! Pokémon) and Community are separate sources; under Official you can pick Worlds, Internationals, Regionals or Special Events.",
        "Search matches species, players and event names; the Search button re-queries even when nothing changed.",
        "Box ▾ finds teams you can build: all six in your box, or one to three missing. Greyed sprites are the ones you lack; the chip says how many you have. Owned entries only; Megas count as their base species.",
    ),
    "Data & syncing": (
        "Tournaments sync at launch when the last sync is older than six hours or a backlog is waiting; Settings › Sync now always runs.",
        "Limitless allows 50 requests per 5 minutes, so a sync fetches standings in slices and continues next time.",
        "Official events are discovered from Victory Road's season calendars; a few finished events are read per sync, newest Champions events first.",
        f"Database: {DEFAULT_DATABASE_FILENAME} · Preferences: {DEFAULT_PREFERENCES_FILENAME} (PCPT_DATABASE, PCPT_PREFERENCES, PCPT_VR_MAX_PLACEMENT override them).",
        "Layout choices (grid or table, stats on cards, summary panel, show all moves, Meta layout) are remembered between launches.",
    ),
}


class HelpDialog(ft.AlertDialog):
    def __init__(self, *, on_close) -> None:
        super().__init__(modal=False, scrollable=True)
        rows = [
            ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                ft.Container(content=ft.Text(keys, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE), width=140,
                             bgcolor=Palette.SURFACE_3, border_radius=Radius.SM, padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=2)),
                ft.Text(what, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, expand=True),
            ])
            for keys, what in SHORTCUTS
        ]
        sections: list[ft.Control] = [SectionHeader("Keyboard shortcuts", accent=Accent.SETTINGS), ft.Column(spacing=Space.XS, tight=True, controls=rows)]
        accents = {"Box": Accent.BOX, "Teams": Accent.TEAMS, "Meta": Accent.META, "Data & syncing": Accent.SETTINGS}
        for title, tips in TIPS.items():
            sections.append(SectionHeader(title, accent=accents.get(title, Palette.SECONDARY)))
            sections.append(ft.Column(spacing=Space.XS, tight=True, controls=[
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                    ft.Text("•", color=Palette.ON_SURFACE_VARIANT),
                    ft.Text(tip, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, expand=True),
                ])
                for tip in tips
            ]))
        self.title = ft.Text("Help")
        self.content = ft.Container(width=720, content=ft.Column(spacing=Space.MD, tight=True, controls=sections))
        self.actions = [ft.TextButton("Close", on_click=lambda _e: on_close())]
        self.actions_alignment = ft.MainAxisAlignment.END


__all__ = ["HelpDialog", "SHORTCUTS", "TIPS"]
