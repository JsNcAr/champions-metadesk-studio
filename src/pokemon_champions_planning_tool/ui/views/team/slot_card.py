"""Slot editor: a compact card expanded in place, spanning the grid's width.

Three zones side by side on wide windows (stacked when narrow):
1. build: form (Mega), ability, the format's other mechanics (Tera), item and its guardrails;
2. moves: four move buttons with a clear button each, and the types they hit;
3. spread: the shared stat-point editor inline, with presets and live level-50 stats.
Partners and notes run along the bottom. Controls for mechanics the team's format does
not have are hidden (``MECHANIC_CONTROLS``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import flet as ft

from ....domain.entities.pokemon_stats import PokemonStats
from ....domain.formats import BUILTIN_FORMATS, Format, Mechanic
from ....domain.type_chart import TYPES
from ....services.tournament_service import PartnerRecommendation
from ...components import Sprite, StatusChip
from ...components.banner import InlineBanner
from ...components.item_icon import item_icon
from ...components.pokemon import BstPill, TypeChip
from ...components.spread_editor import SpreadEditor
from ...tasks import is_mounted
from ...theme import IconSize, Motion, Palette, Radius, STAT_COLORS, STAT_LABELS, Space, alpha, type_color
from .dialogs.spread import PRESETS
from .summary import SlotModel

_EMPTY_STATS = PokemonStats(hp=1, attack=1, defense=1, sp_atk=1, sp_def=1, speed=1)


@dataclass
class SlotCallbacks:
    on_assign: Callable[[int], None]
    on_clear: Callable[[int], None]
    on_form: Callable[[int, str], None]
    on_ability: Callable[[int, str], None]
    on_tera: Callable[[int, str | None], None]
    on_item: Callable[[int], None]
    on_remove_item: Callable[[int], None]
    on_notes: Callable[[int, str], None]
    on_swap: Callable[[int, int], None]
    on_focus: Callable[[int], None]
    on_move_pick: Callable[[int, int], None] = lambda position, index: None
    on_clear_move: Callable[[int, int], None] = lambda position, index: None
    on_spread_change: Callable[[int, str, dict[str, int]], None] = lambda position, nature, points: None
    on_collapse: Callable[[int], None] = lambda position: None
    on_step: Callable[[int, int], None] = lambda position, delta: None
    on_apply_build: Callable[[int, bool], None] = lambda position, moves_only: None
    on_partner: Callable[[str], None] = lambda name: None
    on_calc: Callable[[int], None] = lambda position: None


_CATEGORY_ICONS = {
    "physical": (ft.Icons.SPORTS_MMA, "Physical"),
    "special": (ft.Icons.AUTO_AWESOME, "Special"),
    "status": (ft.Icons.SHIELD_OUTLINED, "Status"),
}
_TARGETS = {"allAdjacentFoes": "Hits both foes", "allAdjacent": "Hits everyone else on the field", "self": "Targets the user",
            "adjacentAlly": "Targets the ally", "allySide": "Affects your side", "foeSide": "Affects the foes' side", "all": "Affects the whole field"}


class MoveButton(ft.Container):
    """One move slot: ``● Fake Out · Normal · 40`` or ``Move 2…``; amber when flagged."""

    def __init__(self, *, index: int, on_click: Callable[[], None]) -> None:
        super().__init__()
        self.index = index
        self._name = ft.Text(f"Move {index + 1}…", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.DISABLED, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._meta = ft.Text("", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._category = ft.Icon(ft.Icons.CIRCLE, size=14, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._stab = ft.Container(content=ft.Text("STAB", size=9, weight=ft.FontWeight.W_700, color=Palette.ON_PRIMARY), bgcolor=Palette.PRIMARY,
                                  border_radius=Radius.PILL, padding=ft.Padding.symmetric(horizontal=4), visible=False,
                                  tooltip="Same-type attack bonus: ×1.5")
        self._warn = ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, size=IconSize.SM, color=Palette.WARNING, visible=False)
        # The category icon carries the move's type colour (the dot it replaced left the name
        # too little room).
        self.content = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                              controls=[self._category, self._name, self._stab, self._meta, self._warn])
        self.height = 36
        self.expand = True
        self.padding = ft.Padding.symmetric(horizontal=Space.MD)
        self.border_radius = Radius.SM
        self.bgcolor = Palette.SURFACE_3
        self.border = ft.Border.all(1, Palette.OUTLINE)
        self.ink = True
        self.on_click = lambda _e: on_click()
        self.tooltip = "Choose move"

    def update_from(self, move, *, species: str, types: tuple[str, ...] | list[str] = ()) -> None:
        self._category.visible = False
        self._stab.visible = False
        if move is None or not move.name:
            self._name.value = f"Move {self.index + 1}…"
            self._name.color = Palette.DISABLED
            self._meta.value = ""
            self._warn.visible = False
            self.border = ft.Border.all(1, Palette.OUTLINE)
            self.tooltip = "Choose move"
            return
        self._name.value = move.name
        self._name.color = Palette.ON_SURFACE
        info = move.info
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
        category = (info.category or "").lower() if info is not None else ""
        if category in _CATEGORY_ICONS:
            self._category.icon, label = _CATEGORY_ICONS[category]
            self._category.tooltip = f"{(info.type or '').capitalize()} · {label}".strip(" ·")
            self._category.color = type_color(info.type) if info is not None and info.type else Palette.ON_SURFACE_VARIANT
            self._category.visible = True
        if info is not None and category != "status":
            accuracy = f"{info.accuracy}%" if info.accuracy else "—"
            self._meta.value = f"{info.power or '—'} · {accuracy}"
            self._stab.visible = bool(info.type) and info.type.lower() in {t.lower() for t in types}
        else:
            self._meta.value = "Status" if category == "status" else ""
        details = []
        if info is not None:
            if info.priority:
                details.append(f"Priority {info.priority:+d}")
            if info.target in _TARGETS:
                details.append(_TARGETS[info.target])
            if info.short_desc:
                details.append(info.short_desc)
        head = (f"Not in {species}'s Champions learnset" if flagged else "") + ("\n" if flagged and bits else "") + " · ".join(bits)
        self.tooltip = "\n".join([h for h in [head, *details] if h]) or "Choose move"


class SlotCard(ft.Container):
    """The slot editor. ``update_from`` works whether or not it is on screen, so the view
    keeps all six current and shows the expanded one."""

    def __init__(self, position: int, callbacks: SlotCallbacks) -> None:
        super().__init__()
        self.position = position
        self.cb = callbacks
        self._focused = False
        self._filled = False
        self._spread_key: tuple | None = None

        # -- empty state --------------------------------------------------------------------
        self._empty = ft.Column(
            alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=Space.SM,
            controls=[
                ft.Text(f"Slot {position}", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT),
                ft.FilledTonalButton("Assign Pokémon", icon=ft.Icons.ADD, on_click=lambda _e: self.cb.on_assign(self.position)),
            ],
        )

        # -- header ----------------------------------------------------------------------------
        # The pane header: step through the slots, the tournament set, the slot menu, close.
        self._prev = ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="Previous Pokémon (Alt+←)", on_click=lambda _e: self.cb.on_step(self.position, -1))
        self._next = ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="Next Pokémon (Alt+→)", on_click=lambda _e: self.cb.on_step(self.position, 1))
        self._slot_label = ft.Text(f"Slot {position}", theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=Palette.ON_SURFACE_VARIANT)
        self._build_line = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._build_menu = ft.PopupMenuButton(
            visible=False, tooltip="The most used set for this species in tournaments",
            content=ft.Row(spacing=Space.XS, tight=True, controls=[ft.Icon(ft.Icons.EMOJI_EVENTS_OUTLINED, size=IconSize.SM, color=Palette.PRIMARY),
                                                                   ft.Text("Tournament set", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.PRIMARY),
                                                                   ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=18, color=Palette.PRIMARY)]),
            items=[],
        )
        self._badge = ft.Container(content=ft.Text(str(position), theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE),
                                   width=22, height=22, border_radius=Radius.PILL, bgcolor=Palette.SURFACE_4, alignment=ft.Alignment.CENTER)
        self.sprite = Sprite(size=48)
        self._name = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, color=Palette.ON_SURFACE, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._form_caption = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._types = ft.Row(spacing=Space.XS, tight=True)
        self._bst = BstPill()
        self._planned = StatusChip("Planned", "tertiary", icon=ft.Icons.EDIT_NOTE)
        self._menu = ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, tooltip="Slot actions", items=[])
        self._collapse = ft.IconButton(icon=ft.Icons.CLOSE, tooltip="Close the editor (Esc)", on_click=lambda _e: self.cb.on_collapse(self.position))
        self._header = ft.Container(
            content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                self._prev, self._badge, self.sprite,
                ft.Column(spacing=2, tight=True, expand=True, controls=[
                    ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._name, self._form_caption]),
                    ft.Row(spacing=Space.SM, tight=True, controls=[self._types, self._bst, self._planned]),
                ]),
                self._build_menu, self._slot_label, self._next, self._menu, self._collapse,
            ]),
            padding=ft.Padding.symmetric(horizontal=Space.MD, vertical=Space.SM),
            border_radius=ft.BorderRadius.only(top_left=Radius.MD, top_right=Radius.MD),
        )

        # -- zone 1: build -----------------------------------------------------------------------
        self._form = ft.SegmentedButton(
            selected=["base"], allow_multiple_selection=False, allow_empty_selection=False, show_selected_icon=False,
            segments=[ft.Segment(value="base", label=ft.Text("Base"))], visible=False,
            on_change=lambda e: self.cb.on_form(self.position, next(iter(e.control.selected or ["base"]))),
        )
        self._ability = ft.Dropdown(label="Ability", options=[], width=200, dense=True,
                                    on_select=lambda e: self.cb.on_ability(self.position, e.control.value or ""))
        self._tera = ft.Dropdown(
            label="Tera", width=150, dense=True,
            options=[ft.DropdownOption(key="", text="None")] + [ft.DropdownOption(key=t, text=t.capitalize(), leading_icon=ft.Icon(ft.Icons.CIRCLE, size=12, color=type_color(t))) for t in TYPES],
            on_select=lambda e: self.cb.on_tera(self.position, e.control.value or None),
        )
        # Controls that exist only when the team's format has the mechanic. A new mechanic
        # registers its control here (and in domain.formats) and appears where the format allows it.
        self.mechanic_controls: dict[Mechanic, ft.Control] = {Mechanic.MEGA: self._form, Mechanic.TERA: self._tera}
        self._item_icon = ft.Container(width=24, height=24, content=item_icon(None))    # the item's sprite (or sheet cell)
        self._item_name = ft.Text("Held item…", theme_style=ft.TextThemeStyle.BODY_MEDIUM, color=Palette.ON_SURFACE_VARIANT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self._item_clear = ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, width=28, height=28, padding=0, tooltip="Remove item", visible=False,
                                         on_click=lambda _e: self.cb.on_remove_item(self.position))
        self._item_button = ft.Container(
            content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._item_icon, self._item_name, ft.Icon(ft.Icons.CHEVRON_RIGHT, size=IconSize.SM, color=Palette.ON_SURFACE_VARIANT)]),
            height=40, padding=ft.Padding.symmetric(horizontal=Space.MD), border_radius=Radius.SM, bgcolor=Palette.SURFACE_3, border=ft.Border.all(1, Palette.OUTLINE),
            on_click=lambda _e: self.cb.on_item(self.position), ink=True, tooltip="Choose held item", expand=True,
        )
        self._item_field = ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._item_button, self._item_clear])
        self._item_effect = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS, visible=False)
        self._deltas = ft.Row(spacing=Space.XS, wrap=True, tight=True)
        self._guardrail = InlineBanner(visible=False)
        # Defense: what hits this Pokémon for how much, its ability included.
        self._defense = ft.Column(spacing=Space.XS, tight=True)
        self._defense_note = ft.Text("", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)

        # -- zone 2: moves ---------------------------------------------------------------------
        self._moves = [MoveButton(index=i, on_click=lambda i=i: self.cb.on_move_pick(self.position, i)) for i in range(4)]
        self._move_clears = [ft.IconButton(icon=ft.Icons.CLOSE, icon_size=14, width=28, height=28, padding=0, tooltip="Clear move", visible=False,
                                           on_click=lambda _e, i=i: self.cb.on_clear_move(self.position, i)) for i in range(4)]
        self._coverage_label = ft.Text("Hits SE", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT)
        self._coverage_chips = ft.Row(spacing=Space.XS, tight=True, wrap=True)
        self._coverage = ft.Column(spacing=Space.XS, tight=True, controls=[self._coverage_label, self._coverage_chips])

        # -- zone 3: spread ------------------------------------------------------------------------
        self._spread_editor = SpreadEditor(base_stats=_EMPTY_STATS, nature=None, points=None, compact=True,
                                           on_change=lambda nature, points: self.cb.on_spread_change(self.position, nature, points))
        self._spread_banner = InlineBanner(visible=False)
        self._presets = ft.PopupMenuButton(
            tooltip="Spread presets",
            content=ft.Row(spacing=Space.XS, tight=True, controls=[ft.Icon(ft.Icons.AUTO_FIX_HIGH, size=IconSize.SM, color=Palette.PRIMARY),
                                                                   ft.Text("Presets", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.PRIMARY)]),
            items=[
                *[ft.PopupMenuItem(content=ft.Text(name), on_click=lambda _e, name=name, pts=pts: self._preset(name, pts)) for name, pts in PRESETS.items()],
                ft.PopupMenuItem(),
                ft.PopupMenuItem(content=ft.Text("Min speed (0 points, −Spe nature)"), on_click=lambda _e: self._spread_editor.set_min_speed()),
                ft.PopupMenuItem(content=ft.Text("Reset"), on_click=lambda _e: self._spread_editor.apply_points({})),
            ],
        )
        self._spread_caption = ft.Text("Level 50 · stat points (0–32, 66 in total)", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True)

        # -- footer: partners · notes ----------------------------------------------------------------
        self._partners = ft.Row(spacing=Space.XS, wrap=True, visible=False)
        self._partners_label = ft.Text("Common partners", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, visible=False)
        self._notes = ft.TextField(label="Notes", hint_text="Lead plans, damage benchmarks, what to watch for…", multiline=True, min_lines=1, max_lines=4, dense=True, expand=True,
                                   on_blur=lambda e: self.cb.on_notes(self.position, e.control.value or ""))

        def zone(title: str, controls: list[ft.Control], col: dict, trailing: ft.Control | None = None) -> ft.Container:
            head: list[ft.Control] = [ft.Text(title, theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT, expand=True)]
            if trailing is not None:
                head.append(trailing)
            return ft.Container(col=col, content=ft.Column(spacing=Space.SM, tight=True, controls=[ft.Row(spacing=Space.SM, controls=head), *controls]))

        self._zones = ft.ResponsiveRow(spacing=Space.LG, run_spacing=Space.LG, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
            zone("BUILD", [ft.Row(spacing=Space.SM, wrap=True, controls=[self._form, self._ability, self._tera]), self._item_field, self._item_effect,
                           self._deltas, self._guardrail,
                           ft.Text("DEFENSE", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.ON_SURFACE_VARIANT), self._defense, self._defense_note],
                 {"xs": 12, "md": 6, "xl": 4}),
            zone("MOVES", [*(ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[self._moves[i], self._move_clears[i]]) for i in range(4)),
                           self._coverage, self._partners_label, self._partners], {"xs": 12, "md": 6, "xl": 4}),
            zone("SPREAD", [ft.Row(controls=[self._spread_caption]), self._spread_editor, self._spread_banner], {"xs": 12, "xl": 4}, trailing=self._presets),
        ])
        self._filled_body = ft.Column(spacing=Space.MD, tight=True, controls=[
            self._header,
            ft.Container(padding=ft.Padding.only(left=Space.LG, right=Space.LG, bottom=Space.LG), content=ft.Column(spacing=Space.MD, tight=True, controls=[
                self._zones,
                ft.Row(controls=[self._notes]),
            ])),
        ])
        self._inner = ft.Container(content=self._empty)
        self.content = self._inner
        self.bgcolor = Palette.SURFACE_2
        self.border_radius = Radius.MD
        self.border = ft.Border.all(2, Palette.PRIMARY)
        self.animate = ft.Animation(Motion.FAST_MS, Motion.CURVE)

    # -- model -> controls -----------------------------------------------------------------------

    def update_from(self, slot: SlotModel, *, focused: bool = False, fmt: Format | None = None) -> None:
        self._focused = focused
        fmt = fmt or BUILTIN_FORMATS[0]
        self._filled = slot.filled
        if not slot.filled or slot.form is None:
            self._inner.content = self._empty
            self._inner.padding = Space.LG
            return

        entry, member, form = slot.entry, slot.member, slot.form
        pokemon = entry.pokemon
        primary = form.types[0] if form.types else None
        self._header.bgcolor = alpha(type_color(primary), 0.30)
        self.sprite.set_src(form.sprite_url)
        self.sprite.set_tooltip(pokemon.qualified_name)
        self.sprite.set_ring("planned" if entry.is_planned else ("mega" if form.is_mega else "type"), primary)
        self._name.value = pokemon.display_name
        self._form_caption.value = form.label if form.is_mega else (pokemon.form_name if pokemon.form_name and pokemon.form_name.lower() != "base" else "")
        self._form_caption.visible = bool(self._form_caption.value)
        self._types.controls = [TypeChip(t, size="sm") for t in form.types]
        self._bst.set_total(form.stats.total, (form.stats.total - pokemon.total) if form.is_mega else None)
        self._planned.visible = entry.is_planned
        self._menu.items = self._menu_items()

        choices = slot.form_choices()
        self._form.segments = [ft.Segment(value=c.form_id, label=ft.Text(c.label if not c.is_mega else " ".join(c.label.replace(pokemon.display_name, "").split()) or c.label)) for c in choices]
        self._form.selected = [form.form_id]
        for mechanic, control in self.mechanic_controls.items():
            control.visible = fmt.has(mechanic)
        self._form.visible = self._form.visible and len(choices) > 1

        abilities = slot.ability_options
        current = slot.active_ability or member.ability or (abilities[0] if abilities else "")
        if current and current not in abilities and abilities:
            current = abilities[0]
        options = list(dict.fromkeys(abilities + ([current] if current and current not in abilities else [])))
        self._ability.options = [ft.DropdownOption(key=a, text=a) for a in options] or [ft.DropdownOption(key="", text="—")]
        self._ability.value = current
        self._tera.value = member.tera_type or ""

        if slot.item is not None:
            self._item_name.value = slot.item.display_name
            self._item_name.color = Palette.ON_SURFACE
            self._item_icon.content = item_icon(slot.item.sprite_url, size=24)
            self._item_clear.visible = True
        else:
            self._item_name.value = "Held item…"
            self._item_name.color = Palette.ON_SURFACE_VARIANT
            self._item_icon.content = item_icon(None, size=24)
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
        effect = (slot.item.short_effect or "") if slot.item is not None else ""
        self._item_effect.value = effect
        self._item_effect.tooltip = effect or None
        self._item_effect.visible = bool(effect)
        self._render_defense(slot)

        v = slot.validation
        if v is not None and v.error:
            self._guardrail.show(v.error, "error")
        elif v is not None and v.warning:
            self._guardrail.show(v.warning, "warning")
        elif v is not None and v.unlocked_form and fmt.has(Mechanic.MEGA):
            self._guardrail.show(f"Unlocks {form.label if form.is_mega else 'Mega Evolution'}", "info")
        else:
            self._guardrail.hide()

        moves = list(slot.moves)[:4]
        for i, button in enumerate(self._moves):
            move = moves[i] if i < len(moves) else None
            button.update_from(move, species=pokemon.display_name, types=form.types)
            self._move_clears[i].visible = move is not None and bool(move.name)
        hits = slot.super_effective_against
        has_any_move = any(m is not None and bool(m.name) for m in slot.moves)
        if not slot.damaging_types:
            self._coverage_label.value = "No damaging moves" if has_any_move else "Coverage"
            self._coverage_chips.controls = [] if has_any_move else [ft.Text("Pick moves to see what this slot hits", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.DISABLED)]
        else:
            self._coverage_label.value = f"Hits super-effectively · {len(hits)} types"
            self._coverage_chips.controls = [TypeChip(t, size="sm") for t in hits]

        # The spread editor is only reset when the slot's stored spread changed, so a
        # debounced save does not fight the slider being dragged.
        key = (form.form_id, member.nature, tuple(sorted((member.points or {}).items())))
        if key != self._spread_key:
            self._spread_key = key
            self._spread_editor.set_base_stats(form.stats)
            self._spread_editor.set_values(member.nature, member.points)
        self._notes.value = member.notes or ""
        self._inner.content = self._filled_body
        self._inner.padding = 0

    def _render_defense(self, slot: SlotModel) -> None:
        groups = slot.matchups()
        defense = slot.defense
        rows: list[ft.Control] = []
        for label, pick, tone in (("4×", lambda m: m >= 4.0, Palette.ERROR), ("2×", lambda m: 1.0 < m < 4.0, alpha(Palette.ERROR, 0.75)),
                                  ("½", lambda m: m == 0.5, Palette.SUCCESS), ("¼", lambda m: 0.0 < m <= 0.25, Palette.SUCCESS),
                                  ("Immune", lambda m: m == 0.0, Palette.SECONDARY)):
            types = [t for m, ts in sorted(groups.items(), reverse=True) if pick(m) for t in ts]
            if not types:
                continue
            rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.START, controls=[
                ft.Container(width=60, padding=ft.Padding.only(top=2), content=ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, weight=ft.FontWeight.W_600, color=tone)),
                ft.Row(spacing=Space.XS, run_spacing=Space.XS, wrap=True, expand=True, controls=[TypeChip(t, size="sm") for t in types]),
            ]))
        self._defense.controls = rows or [ft.Text("No weaknesses or resistances", theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT)]
        notes = defense[1] if defense else []
        self._defense_note.value = " · ".join(notes)
        self._defense_note.visible = bool(notes)

    def set_slot_info(self, index: int, total: int) -> None:
        """"2 / 6": this slot's place among the filled ones (the ‹ › buttons step through them)."""
        self._slot_label.value = f"{index} / {total}" if total else f"Slot {self.position}"
        self._prev.disabled = self._next.disabled = total <= 1

    def set_build(self, build) -> None:
        """The species' most used tournament set, or None to hide the menu."""
        if build is None:
            self._build_menu.visible = False
        else:
            bits = [b for b in (build.item, build.ability, (build.nature or "").capitalize() or None) if b]
            moves = ", ".join(m for m in build.moves if m)
            line = " · ".join(bits + ([moves] if moves else []))
            self._build_line.value = line
            self._build_menu.items = [
                ft.PopupMenuItem(content=ft.Text(line, theme_style=ft.TextThemeStyle.BODY_SMALL, color=Palette.ON_SURFACE_VARIANT), disabled=True),
                ft.PopupMenuItem(),
                ft.PopupMenuItem(content=ft.Text("Apply the full set"), icon=ft.Icons.DONE_ALL, on_click=lambda _e: self.cb.on_apply_build(self.position, False)),
                ft.PopupMenuItem(content=ft.Text("Apply the moves only"), icon=ft.Icons.FORMAT_LIST_BULLETED, on_click=lambda _e: self.cb.on_apply_build(self.position, True)),
            ]
            self._build_menu.tooltip = f"Most used in tournaments: {line}"
            self._build_menu.visible = True
        if is_mounted(self._build_menu):
            self._build_menu.update()

    def show_spread_problems(self, problems: list[str]) -> None:
        if problems:
            self._spread_banner.show("; ".join(problems), "error")
        else:
            self._spread_banner.hide()
        if is_mounted(self._spread_banner):
            self._spread_banner.update()

    def set_partners(self, partners: list[PartnerRecommendation]) -> None:
        self._partners.controls = [
            ft.Container(
                content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    Sprite(p.sprite_url, size=24),
                    ft.Text(p.display_name, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE),
                    ft.Text(f"{p.synergy_percentage:.0f}%", theme_style=ft.TextThemeStyle.LABEL_SMALL, color=Palette.SUCCESS),
                ]),
                padding=ft.Padding.only(left=2, right=Space.SM, top=2, bottom=2), border_radius=Radius.PILL, bgcolor=Palette.SURFACE_3, ink=True,
                tooltip=f"With this Pokémon in {p.co_occurrence_count} of {p.total_target_teams} tournament teams · click to see them in Meta",
                on_click=lambda _e, name=p.display_name: self.cb.on_partner(name),
            )
            for p in partners[:5]
        ]
        self._partners.visible = self._partners_label.visible = bool(partners)
        if is_mounted(self._partners):
            self._partners.update()
            self._partners_label.update()

    def set_focused(self, focused: bool) -> None:
        self._focused = focused

    # -- interaction ------------------------------------------------------------------------------------

    def _preset(self, name: str, points: dict[str, int]) -> None:
        self._spread_editor.apply_points(points)
        if name == "Trick Room":
            self._spread_editor.set_min_speed()

    def _menu_items(self) -> list[ft.PopupMenuItem]:
        p = self.position
        items = [
            ft.PopupMenuItem(content=ft.Text("Open in damage calc"), icon=ft.Icons.CALCULATE_OUTLINED, on_click=lambda _e: self.cb.on_calc(p)),
            ft.PopupMenuItem(content=ft.Text("Replace Pokémon…"), icon=ft.Icons.SWAP_HORIZ, on_click=lambda _e: self.cb.on_assign(p)),
        ]
        if p != 1:
            items.append(ft.PopupMenuItem(content=ft.Text("Move to lead"), icon=ft.Icons.VERTICAL_ALIGN_TOP, on_click=lambda _e: self.cb.on_swap(p, 1)))
        items.append(ft.PopupMenuItem(content=ft.Text("Clear slot"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self.cb.on_clear(p)))
        return items


__all__ = ["MoveButton", "SlotCallbacks", "SlotCard"]
