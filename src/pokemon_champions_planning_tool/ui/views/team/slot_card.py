"""Team slot card: identity header, build controls, item, moves, spread, partners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from ....domain.type_chart import TYPES
from ....services.tournament_service import PartnerRecommendation
from ...components import Sprite, StatusChip
from ...components.banner import InlineBanner
from ...components.pokemon import BstPill, TypeChip
from ...tasks import is_mounted
from ...theme import IconSize, Motion, OVERLAY_SHADOW, Palette, Radius, STAT_COLORS, STAT_LABELS, Space, alpha, type_color
from .summary import SlotModel


@dataclass
class SlotCallbacks:
    on_assign: Callable[[int], None]
    on_clear: Callable[[int], None]
    on_form: Callable[[int, str], None]
    on_ability: Callable[[int, str], None]
    on_tera: Callable[[int, str | None], None]
    on_item: Callable[[int], None]
    on_remove_item: Callable[[int], None]
    on_move: Callable[[int, int, str], None]
    on_notes: Callable[[int, str], None]
    on_spread: Callable[[int], None]
    on_swap: Callable[[int, int], None]
    on_focus: Callable[[int], None]
    on_move_pick: Callable[[int, int], None] = lambda position, index: None



SLOT_CARD_MAX_EXTENT = 600      # 3 columns at 1440, 2 beside the summary, 1 below ~1200 with it open
SLOT_CARD_HEIGHT = 404          # header + form/ability/tera row + item + 2×2 moves + footer
SLOT_CARD_WRAP_WIDTH = 430      # narrower tiles wrap form/ability/tera onto extra lines…
SLOT_CARD_HEIGHT_NARROW = 500   # …so the card grows to keep the footer visible


class MoveButton(ft.Container):
    """One move slot on the card: ``● Fake Out`` or ``Move 2…``; red when flagged."""

    def __init__(self, *, index: int, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.index = index
        self._dot = ft.Container(width=8, height=8, border_radius=Radius.PILL, bgcolor=Palette.OUTLINE, visible=False)
        self._name = ft.Text(f"Move {index + 1}…", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.DISABLED, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._warn = ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=IconSize.SM, color=Palette.WARNING, visible=False)
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._dot, self._name, self._warn])
        self.height = 36
        self.expand = True
        self.padding = ft.Padding.symmetric(horizontal=Space.MD)
        self.border_radius = Radius.SM
        self.bgcolor = Palette.SURFACE_3
        self.border = ft.Border.all(1, Palette.OUTLINE)
        self.ink = True
        self.on_click = lambda _e: on_click()
        self.tooltip = "Choose move"

    def update_from(self, move, *, species: str) -> None:
        if move is None or not move.name:
            self._name.value = f"Move {self.index + 1}…"
            self._name.color = Palette.DISABLED
            self._dot.visible = False
            self._warn.visible = False
            self.border = ft.Border.all(1, Palette.OUTLINE)
            self.tooltip = "Choose move"
            return
        self._name.value = move.name
        self._name.color = Palette.ON_SURFACE
        info = move.info
        self._dot.visible = info is not None and bool(info.type)
        self._dot.bgcolor = type_color(info.type) if info is not None and info.type else Palette.OUTLINE
        flagged = move.legal is False
        self._warn.visible = flagged
        self.border = ft.Border.all(1, Palette.WARNING if flagged else Palette.OUTLINE)
        bits = []
        if info is not None:
            bits.append(f"{(info.type or '?').capitalize()} · {(info.category or '?').capitalize()}")
            if info.power:
                bits.append(f"{info.power} power")
            if info.accuracy:
                bits.append(f"{info.accuracy}% accuracy")
        self.tooltip = (f"Not in {species}'s Champions learnset" if flagged else "") + ("\n" if flagged and bits else "") + " · ".join(bits) or "Choose move"


class SlotCard(ft.Container):
    def __init__(self, position: int, callbacks: SlotCallbacks) -> None:
        super().__init__()
        self.position = position
        self.cb = callbacks
        self._focused = False
        self._filled = False

        # -- empty state ------------------------------------------------------------------
        self._empty = ft.Column(
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=Space.SM,
            controls=[
                ft.Text(f"Slot {position}", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT),
                ft.Icon(ft.Icons.ADD_CIRCLE_OUTLINE, size=IconSize.LG, color=Palette.SECONDARY),
                ft.FilledTonalButton("Assign Pokémon", icon=ft.Icons.ADD, on_click=lambda _e: self.cb.on_assign(self.position)),
            ],
        )

        # -- header ---------------------------------------------------------------------------
        self._badge = ft.Container(content=ft.Text(str(position), theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE),
                                   width=22, height=22, border_radius=Radius.PILL, bgcolor=Palette.SURFACE_4, alignment=ft.Alignment.CENTER)
        self.sprite = Sprite(size=56)
        self._name = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._form_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._types = ft.Row(spacing=Space.XS, tight=True)
        self._bst = BstPill()
        self._planned = StatusChip("Planned", "tertiary", icon=ft.Icons.EDIT_NOTE)
        self._menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip="Slot actions", items=[])
        self._header = ft.Container(
            content=ft.Row(
                spacing=Space.SM,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    self._badge,
                    self.sprite,
                    ft.Column(spacing=2, tight=True, expand=True, controls=[self._name, self._form_caption, ft.Row(spacing=Space.SM, tight=True, controls=[self._types, self._bst, self._planned])]),
                    self._menu,
                ],
            ),
            padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM),
            border_radius=ft.BorderRadius.only(top_left=Radius.MD, top_right=Radius.MD),
        )

        # -- build row --------------------------------------------------------------------------
        self._form = ft.SegmentedButton(
            selected=["base"], allow_multiple_selection=False, allow_empty_selection=False, show_selected_icon=False,
            segments=[ft.Segment(value="base", label=ft.Text("Base"))], visible=False,
            on_change=lambda e: self.cb.on_form(self.position, next(iter(e.control.selected or ["base"]))),
        )
        self._ability = ft.Dropdown(label="Ability", options=[], width=170, dense=True,
                                    on_select=lambda e: self.cb.on_ability(self.position, e.control.value or ""))
        self._tera = ft.Dropdown(
            label="Tera", width=140, dense=True,
            options=[ft.DropdownOption(key="", text="None")] + [ft.DropdownOption(key=t, text=t.capitalize(), leading_icon=ft.Icon(ft.Icons.CIRCLE, size=12, color=type_color(t))) for t in TYPES],
            on_select=lambda e: self.cb.on_tera(self.position, e.control.value or None),
        )

        # -- item ---------------------------------------------------------------------------------
        self._item_sprite = ft.Image(src="", width=24, height=24, fit=ft.BoxFit.CONTAIN, visible=False, error_content=ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=18, color=Palette.DISABLED))
        self._item_icon = ft.Icon(ft.Icons.DIAMOND_OUTLINED, size=IconSize.MD, color=Palette.ON_SURFACE_VARIANT)
        self._item_name = ft.Text("Held item…", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._item_clear = ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, width=28, height=28, padding=0, tooltip="Remove item", visible=False,
                                         on_click=lambda _e: self.cb.on_remove_item(self.position))
        self._item_field = ft.Container(
            content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._item_icon, self._item_sprite, self._item_name, self._item_clear, ft.Icon(ft.Icons.CHEVRON_RIGHT, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT)]),
            height=40, padding=ft.Padding.symmetric(horizontal=Space.MD), border_radius=Radius.SM, bgcolor=Palette.SURFACE_3, border=ft.Border.all(1, Palette.OUTLINE),
            on_click=lambda _e: self.cb.on_item(self.position), ink=True, tooltip="Choose held item",
        )
        self._deltas = ft.Row(spacing=Space.XS, wrap=True, tight=True)
        self._guardrail = InlineBanner(visible=False)

        # -- moves ----------------------------------------------------------------------------------
        # Four move buttons: type dot, name, warning when not in the Champions learnset.
        # Clicking opens the move picker for that index.
        self._moves = [MoveButton(index=i, on_click=lambda i=i: self.cb.on_move_pick(self.position, i)) for i in range(4)]
        self._move_values = ["", "", "", ""]

        # -- footer: spread · partners · notes -------------------------------------------------------
        self._spread = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._spread_button = ft.TextButton("Edit spread", icon=ft.Icons.TUNE, on_click=lambda _e: self.cb.on_spread(self.position))
        self._partners = ft.Row(spacing=Space.XS, tight=True, visible=False)
        self._notes_toggle = ft.IconButton(icon=ft.Icons.NOTES, icon_size=IconSize.MD, tooltip="Notes", on_click=lambda _e: self._toggle_notes())
        self._notes = ft.TextField(hint_text="Notes…", multiline=True, min_lines=2, max_lines=4, dense=True, visible=False,
                                   on_blur=lambda e: self.cb.on_notes(self.position, e.control.value or ""))

        self._filled_body = ft.Column(
            spacing=Space.SM,
            tight=True,
            controls=[
                self._header,
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=Space.MD),
                    content=ft.Column(spacing=Space.SM, tight=True, controls=[
                        ft.Row(spacing=Space.SM, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._form, self._ability, self._tera]),
                        self._item_field,
                        self._deltas,
                        self._guardrail,
                        ft.Row(spacing=Space.SM, controls=[self._moves[0], self._moves[1]]),
                        ft.Row(spacing=Space.SM, controls=[self._moves[2], self._moves[3]]),
                        ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._spread, self._spread_button, self._partners, self._notes_toggle]),
                        self._notes,
                    ]),
                ),
                ft.Container(height=Space.SM),
            ],
        )

        # Drag the header onto another card to swap the two slots (or move into an empty one).
        self._drag_name = ft.Text("", theme_style=ft.TextThemeStyle.BODY_LARGE, color=Palette.ON_SURFACE)
        self._drag_handle = ft.Draggable(
            group="team-slot",
            data=position,
            content=self._header,
            content_feedback=ft.Container(
                content=ft.Row(spacing=Space.SM, tight=True, controls=[self._badge_copy(), self._drag_name]),
                bgcolor=Palette.SURFACE_4, border_radius=Radius.MD, padding=Space.SM, shadow=OVERLAY_SHADOW,
            ),
        )
        self._filled_body.controls[0] = self._drag_handle
        self._drop_hover = False
        self._inner = ft.Container(content=self._empty, expand=True)

        self.content = ft.DragTarget(
            group="team-slot",
            content=self._inner,
            on_will_accept=self._on_will_accept,
            on_accept=self._on_accept,
            on_leave=lambda _e: self._set_drop_hover(False),
        )
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(1, Palette.OUTLINE_VARIANT)
        self.animate = ft.Animation(Motion.FAST_MS, Motion.CURVE)
        self.on_click = lambda _e: self.cb.on_focus(self.position)

    # -- model -> controls ------------------------------------------------------------------------

    def update_from(self, slot: SlotModel, *, focused: bool = False) -> None:
        self._focused = focused
        self._filled = slot.filled
        if not slot.filled or slot.form is None:
            self._inner.content = self._empty
            self.padding = Space.LG
            self._apply_frame()
            return

        entry, member, form = slot.entry, slot.member, slot.form
        pokemon = entry.pokemon
        primary = form.types[0] if form.types else None
        self._header.bgcolor = alpha(type_color(primary), 0.30)
        self.sprite.set_src(form.sprite_url)
        self.sprite.set_tooltip(pokemon.display_name)
        self.sprite.set_ring("planned" if entry.is_planned else ("mega" if form.is_mega else "type"), primary)
        self._name.value = pokemon.display_name
        self._form_caption.value = form.label if form.is_mega else (pokemon.form_name if pokemon.form_name and pokemon.form_name.lower() != "base" else "")
        self._form_caption.visible = bool(self._form_caption.value)
        self._types.controls = [TypeChip(t, size="sm") for t in form.types]
        self._bst.set_total(form.stats.total, (form.stats.total - pokemon.total) if form.is_mega else None)
        self._planned.visible = entry.is_planned
        self._menu.items = self._menu_items()

        choices = slot.form_choices()
        self._form.visible = len(choices) > 1
        self._form.segments = [ft.Segment(value=c.form_id, label=ft.Text(c.label if not c.is_mega else c.label.replace(pokemon.display_name, "").strip() or c.label)) for c in choices]
        self._form.selected = [form.form_id]

        abilities = slot.ability_options
        current = member.ability or (abilities[0] if abilities else "")
        options = list(dict.fromkeys(abilities + ([current] if current and current not in abilities else [])))
        self._ability.options = [ft.DropdownOption(key=a, text=a) for a in options] or [ft.DropdownOption(key="", text="—")]
        self._ability.value = current
        self._tera.value = member.tera_type or ""

        if slot.item is not None:
            self._item_name.value = slot.item.display_name
            self._item_name.color = Palette.ON_SURFACE
            self._item_sprite.src = slot.item.sprite_url or ""
            self._item_sprite.visible = bool(slot.item.sprite_url)
            self._item_icon.visible = not slot.item.sprite_url
            self._item_clear.visible = True
        else:
            self._item_name.value = "Held item…"
            self._item_name.color = Palette.ON_SURFACE_VARIANT
            self._item_sprite.visible = False
            self._item_icon.visible = True
            self._item_clear.visible = False

        base, eff = slot.base_stats, slot.effective_stats
        deltas: list[ft.Control] = []
        if base is not None and eff is not None:
            for stat in STAT_COLORS:
                b, e = getattr(base, stat), getattr(eff, stat)
                if e != b and b:
                    pct = round((e - b) / b * 100)
                    deltas.append(StatusChip(f"{STAT_LABELS[stat]} {b} → {e} ({pct:+d}%)", "neutral"))
                    deltas[-1]._label.color = STAT_COLORS[stat]
        self._deltas.controls = deltas
        self._deltas.visible = bool(deltas)

        v = slot.validation
        if v is not None and v.error:
            self._guardrail.show(v.error, "error")
        elif v is not None and v.warning:
            self._guardrail.show(v.warning, "warning")
        elif v is not None and v.unlocked_form:
            self._guardrail.show(f"Unlocks {form.label if form.is_mega else 'Mega Evolution'}", "info")
        else:
            self._guardrail.hide()

        moves = list(slot.moves)[:4]
        for i, button in enumerate(self._moves):
            move = moves[i] if i < len(moves) else None
            button.update_from(move, species=pokemon.display_name)
            self._move_values[i] = move.name if move else ""
        self._spread.value = slot.spread_summary
        self._notes.value = member.notes or ""
        self._notes_toggle.icon = ft.Icons.NOTES if not member.notes else ft.Icons.STICKY_NOTE_2
        self._notes_toggle.icon_color = Palette.PRIMARY if member.notes else Palette.ON_SURFACE_VARIANT

        self._drag_name.value = pokemon.display_name
        self._inner.content = self._filled_body
        self.padding = 0
        self._apply_frame()

    def set_partners(self, partners: list[PartnerRecommendation]) -> None:
        self._partners.controls = [
            Sprite(p.sprite_url, size=24, tooltip=f"{p.display_name} · with this Pokémon in {p.co_occurrence_count} of {p.total_target_teams} tournament teams ({p.synergy_percentage:.0f}%)")
            for p in partners[:3]
        ]
        if partners:
            self._partners.controls.append(ft.Text(f"{partners[0].synergy_percentage:.0f}%", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.SUCCESS, tooltip="Top partner co-occurrence"))
        self._partners.visible = bool(partners)
        if is_mounted(self._partners):
            self._partners.update()

    def set_focused(self, focused: bool) -> None:
        self._focused = focused
        self._apply_frame()

    # -- interaction ------------------------------------------------------------------------------------

    def _menu_items(self) -> list[ft.PopupMenuItem]:
        others = [p for p in range(1, 7) if p != self.position]
        return [
            ft.PopupMenuItem(content=ft.Text("Replace Pokémon…"), icon=ft.Icons.SWAP_HORIZ, on_click=lambda _e: self.cb.on_assign(self.position)),
            *([ft.PopupMenuItem(content=ft.Text("Move to lead"), icon=ft.Icons.VERTICAL_ALIGN_TOP, on_click=lambda _e: self.cb.on_swap(self.position, 1))] if self.position != 1 else []),
            *[ft.PopupMenuItem(content=ft.Text(f"Swap with slot {p}"), icon=ft.Icons.SWAP_VERT, on_click=lambda _e, p=p: self.cb.on_swap(self.position, p)) for p in others],
            ft.PopupMenuItem(content=ft.Text("Clear slot"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self.cb.on_clear(self.position)),
        ]


    def _toggle_notes(self) -> None:
        self._notes.visible = not self._notes.visible
        if is_mounted(self._notes):
            self._notes.update()

    def _badge_copy(self) -> ft.Container:
        return ft.Container(content=ft.Text(str(self.position), theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE),
                            width=22, height=22, border_radius=Radius.PILL, bgcolor=Palette.SURFACE_3, alignment=ft.Alignment.CENTER)

    # -- drag and drop -------------------------------------------------------------------------------

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
        self._drop_hover = hovering
        self._apply_frame()
        if is_mounted(self):
            self.update()

    def _apply_frame(self) -> None:
        if self._drop_hover:
            self.border = ft.Border.all(2, Palette.PRIMARY)
            self.bgcolor = Palette.SURFACE_3
            return
        self.bgcolor = Palette.SURFACE_2
        self.border = ft.Border.all(2, Palette.PRIMARY) if self._focused else ft.Border.all(1, Palette.OUTLINE_VARIANT)
