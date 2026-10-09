"""Small pieces shared by the Plans view: a species sprite, a difficulty chip, a plan row."""

from __future__ import annotations

from collections.abc import Callable

import flet as ft

from ....domain.pokemon_identity import get_pokemon_sprite_url
from ...components import Sprite, StatusChip
from ...tasks import is_mounted
from ...theme import Accent, IconSize, Motion, Palette, Radius, Space, alpha
from .model import DIFFICULTIES, Plan

# Not rated, Very easy … Very hard
_DIFFICULTY_TONES = ("neutral", "success", "success", "info", "warning", "error")


def species_sprite(canonical_id: str | None, catalogs, *, size: int = 32, tooltip: str | None = None, ring: str | None = None) -> Sprite:
    species = catalogs.species_for(canonical_id) if canonical_id else None
    is_mega = bool(species and species.is_mega)
    primary_type = species.types_lower[0] if species and species.types_lower else None
    name = species.name if species else (canonical_id or "").replace("-", " ").title()
    return Sprite(get_pokemon_sprite_url(canonical_id) if canonical_id else None, size=size,
                  ring=ring or ("mega" if is_mega else "type"), primary_type=primary_type, tooltip=tooltip or name or None)


def difficulty_chip(value: int) -> StatusChip:
    value = value if 0 <= value < len(DIFFICULTIES) else 0
    return StatusChip(DIFFICULTIES[value] if value else "Not rated", _DIFFICULTY_TONES[value])


class PlanRow(ft.Container):
    """One plan in the list: name, difficulty and the opposing six."""

    def __init__(self, plan: Plan, catalogs, *, selected: bool, on_select: Callable[[str], None], menu_items: list[ft.PopupMenuItem]) -> None:
        super().__init__()
        self.plan = plan
        self._selected = selected
        sprites = ft.Row(spacing=0, controls=[species_sprite(m.pokemon.species, catalogs, size=24) for m in plan.opponent[:6]])
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Column(spacing=4, tight=True, expand=True, controls=[
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Text(plan.name, theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True, tooltip=plan.name),
                    difficulty_chip(plan.difficulty),
                ]),
                sprites,
            ]),
            ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_size=IconSize.SM, tooltip="Plan actions", items=menu_items),
        ])
        self.padding = ft.Padding.only(left=Space.MD, right=Space.XS, top=Space.SM, bottom=Space.SM)
        self.border_radius = Radius.SM
        self.ink = True
        self.on_click = lambda _e: on_select(plan.plan_id)
        self.on_hover = self._hover
        self.animate = ft.Animation(Motion.FAST_MS, Motion.CURVE)
        self._paint(False)

    def _paint(self, hovering: bool) -> None:
        if self._selected:
            self.bgcolor = alpha(Accent.PLANS, 0.14)
            self.border = ft.Border.only(left=ft.BorderSide(3, Accent.PLANS))
        else:
            self.bgcolor = Palette.SURFACE_3 if hovering else None
            self.border = ft.Border.only(left=ft.BorderSide(3, ft.Colors.TRANSPARENT))

    def _hover(self, e: ft.ControlEvent) -> None:
        self._paint(getattr(e, "data", None) in ("true", True))
        if is_mounted(self):
            self.update()


def section(title: str, *controls: ft.Control, trailing: list[ft.Control] | None = None, tip: str | None = None) -> ft.Container:
    """A titled block of the editor, in the same card style as the other views' panels."""
    head: list[ft.Control] = [ft.Text(title.upper(), theme_style=ft.TextThemeStyle.LABEL_SMALL, weight=ft.FontWeight.W_600, color=Accent.PLANS)]
    if tip:
        head.append(ft.Icon(ft.Icons.INFO_OUTLINE, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT, tooltip=tip))
    head.append(ft.Container(expand=True))
    head += trailing or []
    return ft.Container(
        content=ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,   # full-width text fields
                          controls=[ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=head), *controls]),
        bgcolor=Palette.SURFACE_2, border=ft.Border.all(1, Palette.OUTLINE_VARIANT), border_radius=Radius.MD, padding=Space.CARD_PADDING,
    )


__all__ = ["PlanRow", "difficulty_chip", "section", "species_sprite"]
