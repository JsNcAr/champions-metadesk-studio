"""Compact slot card: the team at a glance, six of them on one screen.

Sprite, name and types; item and ability; the four moves; nature, spread and level-50
speed. Clicking the card expands it in place into the full editor (``SlotCard``). The
handle at its top-left drags it onto another card to swap the two slots.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from ...components import Sprite
from ...components.pokemon import TypeChip
from ...tasks import is_mounted
from ...theme import IconSize, Motion, OVERLAY_SHADOW, Palette, Radius, Space, alpha, type_color
from .summary import SlotModel

COMPACT_HEIGHT = 146


@dataclass
class CompactCallbacks:
    on_expand: Callable[[int], None]
    on_assign: Callable[[int], None]
    on_swap: Callable[[int, int], None]
    on_clear: Callable[[int], None]
    on_calc: Callable[[int], None]


def _move_line(move) -> ft.Control:
    """``● Fake Out``: a type dot and the name, or a dim placeholder."""
    if move is None or not move.name:
        return ft.Text("—", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.DISABLED, expand=True)
    info = move.info
    flagged = move.legal is False
    return ft.Row(spacing=Space.XS, expand=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
        ft.Container(width=7, height=7, border_radius=Radius.PILL, bgcolor=type_color(info.type) if info is not None and info.type else Palette.OUTLINE),
        ft.Text(move.name, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.WARNING if flagged else Palette.ON_SURFACE, max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS, expand=True, tooltip="Not in the Champions learnset" if flagged else None),
    ])


class CompactSlot(ft.Container):
    def __init__(self, position: int, callbacks: CompactCallbacks) -> None:
        super().__init__()
        self.position = position
        self.cb = callbacks
        self._focused = False
        self._drop_hover = False
        self._filled = False

        self._badge = ft.Container(content=ft.Text(str(position), theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE),
                                   width=20, height=20, border_radius=Radius.PILL, bgcolor=Palette.SURFACE_4, alignment=ft.Alignment.CENTER)
        self.sprite = Sprite(size=40)
        self._name = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS)
        self._types = ft.Row(spacing=Space.XS, tight=True)
        self._warn = ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=IconSize.SM, color=Palette.WARNING, visible=False)
        self._menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_size=IconSize.MD, tooltip="Slot actions", items=[])
        self._grip = ft.Icon(ft.Icons.DRAG_INDICATOR, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT, tooltip="Drag onto another slot to swap")
        self._head = ft.Container(
            padding=ft.Padding.only(left=Space.XS, right=0, top=Space.XS, bottom=Space.XS),
            border_radius=ft.BorderRadius.only(top_left=Radius.MD, top_right=Radius.MD),
            content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self._grip, self._badge, self.sprite,
                ft.Column(spacing=2, tight=True, expand=True, controls=[self._name, self._types]),
                self._warn, self._menu,
            ]),
        )
        self._drag_name = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE)
        self.drag_handle = ft.Draggable(
            group="team-slot", data=position, content=self._head,
            content_feedback=ft.Container(content=ft.Row(spacing=Space.SM, tight=True, controls=[self._drag_name]),
                                          bgcolor=Palette.SURFACE_4, border_radius=Radius.MD, padding=Space.SM, shadow=OVERLAY_SHADOW),
        )
        self._item = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self._item_icon = ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=14, color=Palette.ON_SURFACE_VARIANT)
        self._ability = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._moves = ft.Column(spacing=2, tight=True)
        self._spread = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        self._speed = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE, tooltip="Speed at level 50, from the spread and nature")
        self._filled_body = ft.Column(spacing=Space.XS, tight=True, controls=[
            self.drag_handle,
            ft.Container(padding=ft.Padding.symmetric(horizontal=Space.SM), content=ft.Column(spacing=Space.XS, tight=True, controls=[
                ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._item_icon, self._item, self._ability]),
                self._moves,
                ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._spread, self._speed]),
            ])),
        ])
        self._empty = ft.Column(spacing=Space.SM, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text(f"Slot {position}", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT),
            ft.FilledTonalButton("Assign Pokémon", icon=ft.Icons.ADD, on_click=lambda _e: self.cb.on_assign(self.position)),
        ])
        self._inner = ft.Container(content=self._empty, expand=True, alignment=ft.Alignment.CENTER)
        self.content = ft.DragTarget(group="team-slot", content=self._inner, on_will_accept=self._on_will_accept, on_accept=self._on_accept,
                                     on_leave=lambda _e: self._set_drop_hover(False))
        self.height = COMPACT_HEIGHT
        self.border_radius = Radius.MD
        self.ink = True
        self.animate = ft.Animation(Motion.FAST_MS, Motion.CURVE)
        self.on_click = lambda _e: self._clicked()
        self._apply_frame()

    # -- model -> controls ---------------------------------------------------------------------------

    def update_from(self, slot: SlotModel, *, focused: bool = False) -> None:
        self._focused = focused
        self._filled = slot.filled and slot.form is not None
        if not self._filled:
            self._inner.content = self._empty
            self._inner.alignment = ft.Alignment.CENTER
            self.tooltip = None
            self._apply_frame()
            return
        entry, form = slot.entry, slot.form
        primary = form.types[0] if form.types else None
        self._head.bgcolor = alpha(type_color(primary), 0.22)
        self.sprite.set_src(form.sprite_url)
        self.sprite.set_ring("planned" if entry.is_planned else ("mega" if form.is_mega else "type"), primary)
        self._name.value = form.label if form.is_mega else entry.pokemon.display_name
        self._drag_name.value = self._name.value
        self._types.controls = [TypeChip(t, size="sm") for t in form.types]
        self._item.value = slot.item.display_name if slot.item else "No item"
        self._item.color = Palette.ON_SURFACE if slot.item else Palette.DISABLED
        self._ability.value = slot.active_ability or ""
        moves = list(slot.moves)[:4] + [None] * (4 - min(4, len(slot.moves)))
        self._moves.controls = [
            ft.Row(spacing=Space.SM, controls=[_move_line(moves[0]), _move_line(moves[1])]),
            ft.Row(spacing=Space.SM, controls=[_move_line(moves[2]), _move_line(moves[3])]),
        ]
        stats = slot.battle_stats
        self._spread.value = slot.spread_summary or "No spread yet"
        self._speed.value = f"Spe {stats.speed}" if stats else ""
        v = slot.validation
        problems = [x for x in ((v.error if v else None), (v.warning if v else None)) if x] + ([f"{len(slot.illegal_moves)} move(s) outside the learnset"] if slot.illegal_moves else [])
        self._warn.visible = bool(problems)
        self._warn.tooltip = "\n".join(problems) or None
        self._menu.items = self._menu_items()
        self._inner.content = self._filled_body
        self._inner.alignment = ft.Alignment.TOP_CENTER
        self.tooltip = "Edit this slot"
        self._apply_frame()

    def set_focused(self, focused: bool) -> None:
        if focused != self._focused:
            self._focused = focused
            self._apply_frame()

    # -- interaction ------------------------------------------------------------------------------------

    def _clicked(self) -> None:
        if self._filled:
            self.cb.on_expand(self.position)
        else:
            self.cb.on_assign(self.position)

    def _menu_items(self) -> list[ft.PopupMenuItem]:
        p = self.position
        items = [
            ft.PopupMenuItem(content=ft.Text("Edit"), icon=ft.Icons.EDIT_OUTLINED, on_click=lambda _e: self.cb.on_expand(p)),
            ft.PopupMenuItem(content=ft.Text("Open in damage calc"), icon=ft.Icons.CALCULATE_OUTLINED, on_click=lambda _e: self.cb.on_calc(p)),
            ft.PopupMenuItem(content=ft.Text("Replace Pokémon…"), icon=ft.Icons.SWAP_HORIZ, on_click=lambda _e: self.cb.on_assign(p)),
            ft.PopupMenuItem(),
        ]
        if p != 1:
            items.append(ft.PopupMenuItem(content=ft.Text("Move to lead"), icon=ft.Icons.VERTICAL_ALIGN_TOP, on_click=lambda _e: self.cb.on_swap(p, 1)))
            items.append(ft.PopupMenuItem(content=ft.Text("Move left"), icon=ft.Icons.ARROW_BACK, on_click=lambda _e: self.cb.on_swap(p, p - 1)))
        if p != 6:
            items.append(ft.PopupMenuItem(content=ft.Text("Move right"), icon=ft.Icons.ARROW_FORWARD, on_click=lambda _e: self.cb.on_swap(p, p + 1)))
        items += [ft.PopupMenuItem(), ft.PopupMenuItem(content=ft.Text("Clear slot"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self.cb.on_clear(p))]
        return items

    # -- drag and drop -------------------------------------------------------------------------------------

    @staticmethod
    def _source_position(e) -> int | None:
        src = getattr(e, "src", None)
        data = getattr(src, "data", None) if src is not None else getattr(e, "data", None)
        try:
            return int(data) if data is not None else None
        except (TypeError, ValueError):
            return None

    def _on_will_accept(self, e) -> None:
        src = self._source_position(e)
        self._set_drop_hover(src is not None and src != self.position)

    def _on_accept(self, e) -> None:
        src = self._source_position(e)
        self._set_drop_hover(False)
        if src is not None and src != self.position:
            self.cb.on_swap(src, self.position)

    def _set_drop_hover(self, hovering: bool) -> None:
        if hovering == self._drop_hover:
            return
        self._drop_hover = hovering
        self._apply_frame()
        if is_mounted(self):
            self.update()

    def _apply_frame(self) -> None:
        if self._drop_hover:
            self.bgcolor, self.border = Palette.SURFACE_3, ft.Border.all(2, Palette.PRIMARY)
        elif self._focused:
            self.bgcolor, self.border = Palette.SURFACE_2, ft.Border.all(2, Palette.PRIMARY)
        else:
            self.bgcolor = Palette.SURFACE_2 if self._filled else Palette.SURFACE_1
            self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT if self._filled else Palette.OUTLINE)


__all__ = ["COMPACT_HEIGHT", "CompactCallbacks", "CompactSlot"]
