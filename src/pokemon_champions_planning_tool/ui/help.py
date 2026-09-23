"""Help dialog: keyboard shortcuts and the features people would not find by themselves."""

from __future__ import annotations

import flet as ft

from ..config import DEFAULT_DATABASE_FILENAME, DEFAULT_PREFERENCES_FILENAME
from .components import SectionHeader
from .theme import Accent, Palette, Radius, Space

SHORTCUTS: tuple[tuple[str, str], ...] = (
    ("Ctrl+1 / 2 / 3 / 4", "Box · Teams · Meta · Calc"),
    ("Ctrl+,", "Settings"),
    ("F1 or Ctrl+/", "This help"),
    ("Ctrl+F", "Focus the search or filter field (Box, Meta, Calc)"),
    ("Ctrl+Shift+S", "Swap attacker and defender (Calc)"),
    ("Ctrl+B", "Start a battle: enter the rival's team preview (Calc)"),
    ("Ctrl+K", "Add a Pokémon to the box"),
    ("Ctrl+Shift+A", "Select every visible box entry"),
    ("Delete", "Delete the selected box entries (with Undo)"),
    ("Escape", "Close the dialog, then collapse the slot editor or the side panel, then clear the selection"),
    ("Ctrl+L", "All teams: the team library (Teams)"),
    ("Ctrl+N", "New team"),
    ("Ctrl+I", "Import a Showdown paste or Poképaste URL"),
    ("Ctrl+E", "Copy the active team as Showdown text"),
    ("Alt+← / →", "Focus the previous or next slot card (Teams)"),
    ("Alt+Shift+← / →", "Move the focused slot card left or right (Teams)"),
    ("Enter", "Expand the focused slot card into the editor (Teams)"),
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
        "All six slots show as compact cards; click one (or focus it and press Enter) to expand it in place into the editor, and Escape collapses it. Drag a card by its ⠿ handle onto another to swap them; its menu has Move left / right and Move to lead.",
        "The editor has three parts: build (form, ability, item and its checks), moves (× clears one) and the spread, edited inline and saved as you go. Common partners open their tournament teams in Meta.",
        "The analysis panel has four tabs: Health (every check), Stats (level-50 stats; click Spe for the speed order), Types (defensive and offensive coverage) and Roles (speed control, Fake Out, Intimidate, redirection, Protect count…). The chip next to the format sums up the checks and opens Health.",
        "The move picker lists only the species' Champions-legal moves, ranked by tournament usage. \"Show all moves\" in the team menu lists the rest with a warning.",
        "Mega forms use their base species' learnset; picking a Mega Stone switches the form automatically.",
        "The format chip next to the team name picks the rules the team is built for; the cards show only that format's mechanics (Champions: Mega Evolution, no Tera). Settings › Format & mechanics sets the default and creates custom formats, for example one with Terastallization.",
        "Spreads use Champions stat points: 0–32 per stat, 66 in total (level 50 and 31 IVs are fixed). The Presets menu has sweeper and bulky spreads, Trick Room and Min speed (0 points + a −Spe nature).",
        "The team switcher (the six sprites next to the format) opens the library of every team: search by team or Pokémon, sort by last edit, name or completeness, and open, rename, duplicate, compare, copy or delete a team from its tile.",
        "Compare teams… in the team menu (or Compare with… on a library tile) shows two teams side by side, including uncovered types.",
        "Import from Meta opens the preview pre-filled; illegal species block the import, illegal moves only warn.",
    ),
    "Meta": (
        "Events show their winner only; \"Show N more\" or Expand all reveals the rest. The cards layout opens a full standings dialog per event.",
        "Official (Play! Pokémon) and Community are separate sources; under Official you can pick Worlds, Internationals, Regionals or Special Events.",
        "Search matches species, players and event names; the Search button re-queries even when nothing changed.",
        "Search matches species, players and event names. Exclude Pokémon by prefixing with - or ! (e.g. \"pelipper -archaludon\", \"dondozo -tatsugiri\", or \"-incineroar\"); quotes work for multi-word names (e.g. -\"iron hands\"). The Search button re-queries even when nothing changed.",
        "Box ▾ finds teams you can build: all six in your box, or one to three missing. Greyed sprites are the ones you lack; the chip says how many you have. Owned entries only; Megas count as their base species.",
    ),
    "Calc": (
        "Each move card carries its own result: base power, the type multiplier, the damage range, a bar and the KO text; click a card for the 16 rolls and the full description. Status moves with a known effect (Swords Dance, Tailwind, Will-O-Wisp…) get an Activate toggle that applies it.",
        "The move picker opened from the calculator shows what every move would do to the other Pokémon under the current field, and can be sorted by damage instead of tournament usage.",
        "The strip above the panels toggles Singles/Doubles, Tailwind per side, Trick Room, weather, terrain and rooms with one click; the chips below it set screens, Helping Hand, hazards, Leech Seed and Spikes per side. \"Activate\" next to an ability means it has already triggered (Intimidate applied, Flash Fire lit).",
        "The left rail loads a team member or a box Pokémon as the attacker (click) or the defender (shield button). The Opponents rail runs the attacker against every Champions species: Crushed (you OHKO first), Threat (they KO you first), Wall (four hits or more), Mitigated (you win the race), Neutral; \"Tournament sets\" gives each opponent its four most used roster moves.",
        "Rival team (the switch above the opponents) shows the team you are facing, the \"Current battle\", or a preset you saved to plan against. Team preview (Ctrl+B) takes the six species you see and fills each with its most used tournament set. Load team… starts a battle from, or saves as a preset, a preset, one of your own teams, a paste or a Poképaste link; Meta saves any tournament team as a preset from its calculator menu. Use in battle loads a preset into the Current battle.",
        "Each rival is coloured against the attacker and loads as the Defender in one click (your team rail then colours itself against it); Team vs team shows every pairing. In a battle, what you set on a rival in the Defender panel (item, ability, moves, nature, stat points) is kept and its ? mark drops what you have seen. Presets only change through \"Save Defender to …\", so browsing never overwrites them.",
        "HP scaling moves (Eruption, Flail, Hard Press), weight moves (Heavy Slam, Low Kick) and abilities such as Multiscale read the HP sliders and each species' weight; the Spe chip shows who moves first under Tailwind and Trick Room.",
        "Open in damage calc from a team slot's menu, Damage calc vs… on a Meta team, or Damage calc in the Box detail panel; the last calculation is remembered. The numbers come from a port of the Smogon calculator's Champions module and are checked against it; Terastallization is not in Champions and is not modelled.",
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
        accents = {"Box": Accent.BOX, "Teams": Accent.TEAMS, "Meta": Accent.META, "Calc": Accent.CALC, "Data & syncing": Accent.SETTINGS}
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
