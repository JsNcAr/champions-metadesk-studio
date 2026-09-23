"""Settings › Format & mechanics: the default format, what it allows, and custom formats."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import flet as ft

from ....domain.formats import BUILTIN_FORMATS, GAME_TYPES, MECHANICS, Format, Mechanic, custom_copy
from ...components import Panel, SectionHeader, StatusChip
from ...formats import FormatRegistry
from ...tasks import is_mounted
from ...theme import IconSize, Palette, Space


def mechanic_chips(fmt: Format) -> list[ft.Control]:
    """One chip per mechanic the app knows: on, off, or not supported yet."""
    chips: list[ft.Control] = []
    for mechanic, info in MECHANICS.items():
        if fmt.has(mechanic):
            chips.append(StatusChip(info.label, "success", icon=ft.Icons.CHECK, tooltip=info.description))
        elif info.implemented:
            chips.append(StatusChip(info.label, "neutral", icon=ft.Icons.REMOVE, tooltip=f"Not in this format. {info.description}"))
        else:
            chips.append(StatusChip(info.label, "neutral", icon=ft.Icons.SCHEDULE, tooltip=f"Not supported yet. {info.description}"))
    return chips


def rules_line(fmt: Format) -> str:
    parts = [dict(GAME_TYPES)[fmt.game_type], "level 50", "stat points"]
    if fmt.has(Mechanic.MEGA):
        parts.append("one Mega per team" if fmt.one_mega_per_team else "any number of Megas")
    parts.append("Item Clause" if fmt.item_clause else "items may repeat")
    return " · ".join(parts)


class FormatDialog(ft.AlertDialog):
    """Create or edit a custom format. Mechanics without controls in the app are shown,
    greyed out, so the list reads as what exists and what is coming."""

    def __init__(self, *, registry: FormatRegistry, fmt: Format | None, on_saved: Callable[[Format], None], on_close: Callable[[], None]) -> None:
        super().__init__(modal=True, scrollable=True)
        self._registry = registry
        self._on_saved = on_saved
        editing = fmt is not None and not fmt.builtin
        base = fmt or BUILTIN_FORMATS[0]
        self._format_id = fmt.format_id if editing else registry.new_id()
        self.title = ft.Text("Edit format" if editing else "New custom format")
        self._name = ft.TextField(label="Name", value=fmt.name if editing else f"{base.name} (custom)", autofocus=True, dense=True, width=480)
        self._based_on = ft.Dropdown(label="Start from", dense=True, visible=not editing, value=base.format_id if base.builtin else BUILTIN_FORMATS[0].format_id,
                                     options=[ft.DropdownOption(key=f.format_id, text=f.name) for f in BUILTIN_FORMATS],
                                     on_select=lambda e: self._apply_base(e.control.value))
        self._game_type = ft.SegmentedButton(segments=[ft.Segment(value=k, label=ft.Text(label)) for k, label in GAME_TYPES],
                                             selected=[base.game_type], show_selected_icon=False)
        self._mechanics: dict[Mechanic, ft.Switch] = {}
        rows: list[ft.Control] = []
        for mechanic, info in MECHANICS.items():
            switch = ft.Switch(value=base.has(mechanic) and info.implemented, disabled=not info.implemented)
            self._mechanics[mechanic] = switch
            rows.append(ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                switch,
                ft.Column(spacing=0, tight=True, expand=True, controls=[
                    ft.Text(info.label + ("" if info.implemented else " · not supported yet"), theme_style=ft.TextThemeStyle.BODY_MEDIUM,
                            color=Palette.ON_SURFACE if info.implemented else Palette.DISABLED, weight=ft.FontWeight.W_600),
                    ft.Text(info.description, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
                ]),
            ]))
        self._one_mega = ft.Switch(label="One Mega Evolution per team", value=base.one_mega_per_team)
        self._item_clause = ft.Switch(label="Item Clause (no repeated held items)", value=base.item_clause)
        self._error = ft.Text("", color=Palette.ERROR, theme_style=ft.TextThemeStyle.BODY_SMALL, visible=False)
        self.content = ft.Container(width=480, content=ft.Column(spacing=Space.MD, tight=True, controls=[
            self._name, self._based_on,
            ft.Text("Battle", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT), self._game_type,
            ft.Text("Mechanics", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT), *rows,
            ft.Text("Rules", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT), self._one_mega, self._item_clause,
            self._error,
        ]))
        self.actions = [ft.TextButton("Cancel", on_click=lambda _e: on_close()), ft.FilledButton("Save format", icon=ft.Icons.SAVE_OUTLINED, on_click=lambda _e: self.save())]
        self.actions_alignment = ft.MainAxisAlignment.END

    def _apply_base(self, format_id: str | None) -> None:
        base = next((f for f in BUILTIN_FORMATS if f.format_id == format_id), BUILTIN_FORMATS[0])
        self._game_type.selected = [base.game_type]
        for mechanic, switch in self._mechanics.items():
            switch.value = base.has(mechanic) and MECHANICS[mechanic].implemented
        self._one_mega.value = base.one_mega_per_team
        self._item_clause.value = base.item_clause
        if is_mounted(self):
            self.update()

    def build_format(self) -> Format:
        base = next((f for f in BUILTIN_FORMATS if f.format_id == self._based_on.value), BUILTIN_FORMATS[0])
        return replace(
            custom_copy(base, self._format_id, (self._name.value or "").strip()),
            game_type=(self._game_type.selected or ["doubles"])[0],
            mechanics=frozenset(m for m, switch in self._mechanics.items() if switch.value),
            one_mega_per_team=bool(self._one_mega.value), item_clause=bool(self._item_clause.value),
        )

    def save(self) -> None:
        fmt = self.build_format()
        if not fmt.name:
            self._error.value, self._error.visible = "Name the format", True
        elif any(f.name.lower() == fmt.name.lower() and f.format_id != fmt.format_id for f in self._registry.all()):
            self._error.value, self._error.visible = f"A format named “{fmt.name}” already exists", True
        else:
            self._on_saved(self._registry.save_custom(fmt))
            return
        if is_mounted(self._error):
            self._error.update()


class FormatPanel(Panel):
    def __init__(self, *, registry: FormatRegistry, on_edit: Callable[[Format | None], None], on_delete: Callable[[Format], None],
                 on_default: Callable[[str], None]) -> None:
        default_dropdown = ft.Dropdown(label="Default format", width=380, dense=True, on_select=lambda e: on_default(e.control.value or ""))
        chips = ft.Row(spacing=Space.XS, wrap=True)
        rules = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        custom = ft.Column(spacing=Space.XS, tight=True)
        super().__init__([
            SectionHeader("Format & mechanics"),
            ft.Text("The rules teams are built for. The team builder shows controls only for the mechanics a format has: "
                    "Pokémon Champions has Mega Evolution but no Terastallization, Z-Moves or Dynamax. A team can pick its own "
                    "format from the Teams header; the others follow this default.",
                    theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
            ft.Row(spacing=Space.MD, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Icon(ft.Icons.RULE, size=IconSize.LG, color=Palette.ON_SURFACE_VARIANT), default_dropdown]),
            chips, rules,
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                ft.Text("Custom formats", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE_VARIANT),
                ft.TextButton("New custom format…", icon=ft.Icons.ADD, on_click=lambda _e: on_edit(None)),
            ]),
            custom,
        ])
        self._registry = registry
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._default = default_dropdown
        self._chips = chips
        self._rules = rules
        self._custom = custom
        self.render()

    def render(self) -> None:
        default = self._registry.default()
        self._default.options = [ft.DropdownOption(key=f.format_id, text=f.name) for f in self._registry.all()]
        self._default.value = default.format_id
        self._chips.controls = mechanic_chips(default)
        self._rules.value = rules_line(default)
        customs = self._registry.custom()
        if not customs:
            self._custom.controls = [ft.Text("None yet. Create one to switch on a mechanic Champions doesn't have, such as Terastallization.",
                                             theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.DISABLED)]
        else:
            self._custom.controls = [
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Column(spacing=0, tight=True, expand=True, controls=[
                        ft.Text(f.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE, weight=ft.FontWeight.W_600),
                        ft.Text(f"{f.mechanics_label} · {rules_line(f)}", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT),
                    ]),
                    ft.IconButton(icon=ft.Icons.EDIT_OUTLINED, icon_size=IconSize.MD, tooltip="Edit", on_click=lambda _e, f=f: self._on_edit(f)),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_size=IconSize.MD, tooltip="Delete", on_click=lambda _e, f=f: self._on_delete(f)),
                ])
                for f in customs
            ]
        if is_mounted(self):
            self.update()


__all__ = ["FormatDialog", "FormatPanel", "mechanic_chips", "rules_line"]
