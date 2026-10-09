"""The plan editor's Battle flow: a card per opposing lead, each opening to its turns.

A turn row has your two Pokémon on the field (worked out from the lead, switches and KOs)
with what each does: a move from its moveset (and a target when there is a choice), a
switch, Mega Evolution; under each attack its damage. "If…" blocks sit after their turn.
Every change goes through the pure helpers in ``flow`` and is saved straight away; only
the card that changed is redrawn.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any

import flet as ft

from ...components import StatusChip
from ...tasks import is_mounted
from ...theme import Accent, IconSize, Palette, Radius, Space, alpha
from ..calc.state import PokemonState
from .components import species_sprite
from .flow import (
    MAX_BRANCH_TURNS,
    MAX_BRANCHES,
    MAX_TURNS,
    RATING_LABELS,
    RATINGS,
    Action,
    Board,
    Names,
    OppRef,
    Scenario,
    Turn,
    Where,
    action_label,
    add_branch,
    add_turn,
    board_at,
    brought,
    default_target,
    foes_at,
    remove_branch,
    remove_turn,
    scenario_title,
    set_action,
    set_branch,
    set_turn,
    validate,
)
from .flow_calc import Hit, HitKey, form_for, hit_text
from .model import MAX_PICKS, MemberRef, Plan

_RATING_TONES = {"favourable": "success", "even": "info", "unfavourable": "error", "": "neutral"}

FLOW_TIP = (
    "What you do for each opposing lead: your two actions per turn (a move and its target, a switch, Mega Evolution) "
    "and “If…” plans for when things go wrong (one of yours KO'd and who comes in). Only your side is planned; "
    "who is on your field follows the switches and KOs. Each attack shows its damage under the grid's field."
)


@dataclass
class FlowActions:
    add: Callable[[bool], None]                       # True: "Any other lead"; False: asks for their lead pair
    save: Callable[[Scenario], None]
    delete: Callable[[Scenario], None]
    move: Callable[[Scenario, int], None]
    pick_pair: Callable[..., None]                    # (title, selected, allow_clear, on_pick)
    open_hit: Callable[[Scenario, HitKey, int], None]
    pin_hit: Callable[[Scenario, HitKey, int], None]


@dataclass
class FlowContext:
    plan: Plan
    mine: dict[str, PokemonState]          # box entry id -> the member's set
    order: list[str]                       # the team's box entry ids, slot order
    names: Names
    can_mega: Callable[[str], bool]
    move_target: Callable[[str], str | None]   # a move's Showdown target
    catalogs: Any


def _pill(label: str, *, on: bool = True, icon: str | None = None, width: int | None = None) -> ft.Container:
    controls: list[ft.Control] = []
    if icon:
        controls.append(ft.Icon(icon, size=IconSize.SM, color=Accent.PLANS if on else Palette.ON_SURFACE_VARIANT))
    controls += [ft.Text(label, theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT,
                         weight=ft.FontWeight.W_600 if on else ft.FontWeight.W_500, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                         expand=width is not None),
                 ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=16, color=Palette.ON_SURFACE_VARIANT)]
    return ft.Container(
        content=ft.Row(spacing=Space.XS, tight=width is None, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls),
        width=width, height=30, padding=ft.Padding.only(left=Space.SM, right=Space.XS), border_radius=Radius.PILL,
        bgcolor=alpha(Accent.PLANS, 0.14) if on else Palette.SURFACE_2, border=ft.Border.all(1, Accent.PLANS if on else Palette.OUTLINE_VARIANT),
    )


def _small(text: str, *, color: str = Palette.ON_SURFACE_VARIANT, **kw: Any) -> ft.Text:
    return ft.Text(text, theme_style=ft.TextThemeStyle.LABEL_MEDIUM, color=color, **kw)


class ScenarioCard(ft.Container):
    def __init__(self, sc: Scenario, *, ctx: FlowContext, actions: FlowActions, opened: bool, hits: dict[HitKey, tuple[Hit, ...]] | None,
                 on_toggle: Callable[[str], None]) -> None:
        super().__init__()
        self.sc, self.ctx, self.actions = sc, ctx, actions
        self.opened = opened
        self.hits = hits
        self._on_toggle = on_toggle
        self.bgcolor = Palette.SURFACE_3
        self.border_radius = Radius.SM
        self.padding = Space.SM
        self.data = {"scenario": sc.scenario_id}
        self.render()

    # -- layout -----------------------------------------------------------------------------

    def render(self) -> None:
        controls: list[ft.Control] = [self._header()]
        if self.opened:
            controls += self._body()
        self.content = ft.Column(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=controls)

    def refresh(self) -> None:
        self.render()
        if is_mounted(self):
            self.update()

    def _header(self) -> ft.Control:
        sc, ctx = self.sc, self.ctx
        names = ctx.names
        lead, back = brought(ctx.plan, sc)
        issues = validate(ctx.plan, sc, ctx.mine, can_mega=ctx.can_mega, name=names.member)
        sprites = ft.Row(spacing=0, controls=[species_sprite(self._opp_species(o.index), ctx.catalogs, size=30) for o in sc.their_lead]) \
            if sc.their_lead else ft.Icon(ft.Icons.HELP_OUTLINE, size=IconSize.MD, color=Palette.ON_SURFACE_VARIANT)
        rating = ft.PopupMenuButton(
            tooltip="How this lead goes for you",
            content=StatusChip(RATING_LABELS.get(sc.rating, "Rate it"), _RATING_TONES.get(sc.rating, "neutral")),
            items=[ft.PopupMenuItem(content=ft.Text(label), on_click=lambda _e, k=key: self._save(replace(self.sc, rating=k))) for key, label in RATINGS]
                  + [ft.PopupMenuItem(content=ft.Text("Not rated"), on_click=lambda _e: self._save(replace(self.sc, rating="")))],
        )
        summary = f"Lead {' + '.join(names.member(r) for r in lead) or '—'}" + (f" · Back {' + '.join(names.member(r) for r in back)}" if back else "")
        steps = len(sc.turns) + sum(len(b.turns) for b in sc.branches)
        head: list[ft.Control] = [
            ft.Icon(ft.Icons.EXPAND_LESS if self.opened else ft.Icons.EXPAND_MORE, size=IconSize.MD, color=Palette.ON_SURFACE_VARIANT),
            sprites,
            ft.Column(spacing=0, tight=True, expand=True, controls=[
                ft.Text(scenario_title(sc, names), theme_style=ft.TextThemeStyle.BODY_MEDIUM, weight=ft.FontWeight.W_600, color=Palette.ON_SURFACE,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                _small(f"{summary} · {steps} turn{'s' if steps != 1 else ''}" + (f" · {len(sc.branches)} “If…”" if sc.branches else ""),
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ]),
            rating,
        ]
        if issues:
            lines = [f"T{sc.turn_number(i.where, i.turn)}: {i.text}" if i.turn is not None else i.text for i in issues]
            head.append(StatusChip(f"{len(issues)} to check", "warning", icon=ft.Icons.WARNING_AMBER_OUTLINED, tooltip="\n".join(lines)))
        menu = [
            ft.PopupMenuItem(content=ft.Text("Move up"), icon=ft.Icons.ARROW_UPWARD, on_click=lambda _e: self.actions.move(self.sc, -1)),
            ft.PopupMenuItem(content=ft.Text("Move down"), icon=ft.Icons.ARROW_DOWNWARD, on_click=lambda _e: self.actions.move(self.sc, 1)),
        ]
        if not sc.is_fallback:
            menu.append(ft.PopupMenuItem(content=ft.Text("Change their lead…"), icon=ft.Icons.SWAP_HORIZ, on_click=lambda _e: self._change_their_lead()))
        menu += [ft.PopupMenuItem(), ft.PopupMenuItem(content=ft.Text("Delete"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self.actions.delete(self.sc))]
        head.append(ft.PopupMenuButton(icon=ft.Icons.MORE_VERT, icon_size=IconSize.SM, tooltip="Scenario actions", items=menu))
        return ft.Container(
            content=ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=head),
            ink=True, border_radius=Radius.SM, on_click=lambda _e: self._on_toggle(self.sc.scenario_id), data={"toggle": True},
        )

    def _body(self) -> list[ft.Control]:
        sc = self.sc
        out: list[ft.Control] = [self._picks_row()]
        for i, turn in enumerate(sc.turns):
            out.append(self._turn_row(None, i, turn))
            out += [self._branch_block(b, br) for b, br in enumerate(sc.branches) if br.after_turn == i + 1]
        out += [self._branch_block(b, br) for b, br in enumerate(sc.branches) if br.after_turn > len(sc.turns)]
        out.append(ft.Row(spacing=Space.SM, controls=[
            ft.TextButton("Add turn", icon=ft.Icons.ADD, disabled=len(sc.turns) >= MAX_TURNS, on_click=lambda _e: self._save(add_turn(self.sc))),
        ]))
        out.append(ft.TextField(value=sc.note, label="Notes for this lead", hint_text="Anything the turns don't say…", dense=True, multiline=True,
                                min_lines=1, max_lines=4, text_size=13,
                                on_blur=lambda e: self._save(replace(self.sc, note=e.control.value or ""), redraw=False)
                                if (e.control.value or "") != self.sc.note else None))
        return out

    # -- lead and back ----------------------------------------------------------------------

    def _picks_row(self) -> ft.Control:
        lead, back = brought(self.ctx.plan, self.sc)
        rows = []
        for role, picked in (("lead", lead), ("back", back)):
            chips = []
            for box in self.ctx.order:
                state = self.ctx.mine.get(box)
                on = any(r.box_entry_id == box for r in picked)
                chips.append(ft.Container(
                    content=ft.Row(spacing=Space.XS, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                        species_sprite(state.species if state else None, self.ctx.catalogs, size=24),
                        _small(self.ctx.names.member(MemberRef(box, state.species if state else "")), color=Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT),
                    ]),
                    padding=ft.Padding.only(left=2, right=Space.SM, top=1, bottom=1), border_radius=Radius.PILL, ink=True,
                    bgcolor=alpha(Accent.PLANS, 0.16) if on else None, border=ft.Border.all(1, Accent.PLANS if on else Palette.OUTLINE_VARIANT),
                    on_click=lambda _e, r=role, b=box: self._toggle_pick(r, b), data={"pick": role, "box": box, "on": on},
                ))
            rows.append(ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                _small("Lead" if role == "lead" else "Back", width=40), ft.Row(spacing=Space.XS, wrap=True, run_spacing=Space.XS, expand=True, controls=chips)]))
        own = bool(self.sc.lead or self.sc.back)
        rows.append(ft.Row(controls=[
            _small("This lead uses its own picks" if own else "Same as the plan's Lead and Back"),
            ft.TextButton("Use the plan's", visible=own, on_click=lambda _e: self._save(replace(self.sc, lead=(), back=()))),
        ]))
        return ft.Column(spacing=Space.XS, tight=True, controls=rows)

    def _toggle_pick(self, role: str, box: str) -> None:
        lead, back = (list(x) for x in brought(self.ctx.plan, self.sc))
        target, other = (lead, back) if role == "lead" else (back, lead)
        state = self.ctx.mine.get(box)
        ref = MemberRef(box, state.species if state else "")
        if any(r.box_entry_id == box for r in target):
            target[:] = [r for r in target if r.box_entry_id != box]
        else:
            target.append(ref)
            target[:] = target[-MAX_PICKS:]
            other[:] = [r for r in other if r.box_entry_id != box]
        self._save(replace(self.sc, lead=tuple(lead), back=tuple(back)))

    # -- turns ------------------------------------------------------------------------------

    def _turn_row(self, where: Where, i: int, turn: Turn) -> ft.Control:
        sc, plan = self.sc, self.ctx.plan
        board = board_at(plan, sc, i, where)
        foes = foes_at(sc, i, where)
        menu = [ft.PopupMenuItem(content=ft.Text("Their field…"), icon=ft.Icons.GROUPS_OUTLINED, on_click=lambda _e: self._their_field(where, i))]
        if where is None:
            menu.append(ft.PopupMenuItem(content=ft.Text("Add “If…” after this turn"), icon=ft.Icons.CALL_SPLIT,
                                         disabled=len(sc.branches) >= MAX_BRANCHES, on_click=lambda _e: self._add_if(i)))
        menu.append(ft.PopupMenuItem(content=ft.Text("Delete turn"), icon=ft.Icons.DELETE_OUTLINE,
                                     on_click=lambda _e: self._save(remove_turn(self.sc, where, i))))
        head = ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text(f"T{sc.turn_number(where, i)}", theme_style=ft.TextThemeStyle.LABEL_LARGE, weight=ft.FontWeight.W_700, color=Accent.PLANS, width=28),
            _small("vs"),
            ft.Row(spacing=0, controls=[species_sprite(self._opp_species(o.index), self.ctx.catalogs, size=24) for o in foes]),
            ft.Container(expand=True),
            ft.PopupMenuButton(icon=ft.Icons.MORE_HORIZ, icon_size=IconSize.SM, tooltip="Turn actions", items=menu),
        ])
        pickers = ft.ResponsiveRow(spacing=Space.SM, run_spacing=Space.SM, controls=[
            self._picker(where, i, slot, board, foes, turn.actions[slot]) for slot in (0, 1)])
        note = ft.TextField(value=turn.note, hint_text="Note (what you expect from them, what to watch for…)", dense=True, text_size=13,
                            on_blur=lambda e: self._save(set_turn(self.sc, where, i, note=e.control.value or ""), redraw=False)
                            if (e.control.value or "") != turn.note else None)
        return ft.Container(
            content=ft.Column(spacing=Space.XS, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[head, pickers, note]),
            border=ft.Border.only(top=ft.BorderSide(1, Palette.OUTLINE_VARIANT)), padding=ft.Padding.only(top=Space.XS),
            data={"turn": (where, i)},
        )

    def _picker(self, where: Where, i: int, slot: int, board: Board, foes: Sequence[OppRef], action: Action) -> ft.Control:
        ctx = self.ctx
        who = board.slot(slot)
        col = {"xs": 12, "md": 6}
        if who is None:
            return ft.Container(col=col, content=_small("No one on this side"), padding=Space.XS)
        state = ctx.mine.get(who.box_entry_id)
        mega_now = board.mega_by == who.box_entry_id or action.mega
        form = form_for(state, mega_now=mega_now, catalogs=ctx.catalogs) if state else None
        moves = [m for m in (state.moves if state else []) if m]

        def set_(new: Action) -> None:
            self._save(set_action(self.sc, where, i, slot, new))

        items = [ft.PopupMenuItem(content=ft.Text(m), on_click=lambda _e, m=m: set_(self._move_action(m, foes, action.mega))) for m in moves]
        if board.bench:
            items.append(ft.PopupMenuItem())
            items += [ft.PopupMenuItem(content=ft.Text(f"Switch → {ctx.names.member(b)}"), icon=ft.Icons.SWAP_HORIZ,
                                       on_click=lambda _e, b=b: set_(Action("switch", switch_to=b))) for b in board.bench]
        items += [ft.PopupMenuItem(), ft.PopupMenuItem(content=ft.Text("Clear"), on_click=lambda _e: set_(Action()))]
        label = action_label(replace(action, mega=False), ctx.names) if action.kind else "Pick an action"
        if action.kind == "move":
            label = action.move   # the target is its own pill (one foe) or a caption (both foes, ally)
        row: list[ft.Control] = [
            species_sprite(form.species if form else who.species, ctx.catalogs, size=32),
            ft.Column(spacing=2, tight=True, expand=True, controls=[
                _small(ctx.names.member(who), color=Palette.ON_SURFACE, weight=ft.FontWeight.W_600),
                ft.Row(spacing=Space.XS, wrap=True, run_spacing=Space.XS, controls=self._action_controls(where, i, slot, action, label, items, foes)),
            ]),
        ]
        if state is not None and ctx.can_mega(who.box_entry_id) and board.mega_by in (None, who.box_entry_id) and action.kind != "switch":
            already = board.mega_by == who.box_entry_id
            on = action.mega or already
            row.append(ft.Container(
                content=ft.Row(spacing=2, tight=True, controls=[
                    ft.Icon(ft.Icons.BOLT, size=IconSize.SM, color=Accent.PLANS if on else Palette.ON_SURFACE_VARIANT),
                    _small("Mega" if not already else "Mega'd", color=Palette.ON_SURFACE if on else Palette.ON_SURFACE_VARIANT)]),
                padding=ft.Padding.symmetric(horizontal=Space.SM, vertical=3), border_radius=Radius.PILL,
                bgcolor=alpha(Accent.PLANS, 0.18) if action.mega else None,
                border=ft.Border.all(1, Accent.PLANS if action.mega else Palette.OUTLINE_VARIANT),
                ink=not already, on_click=None if already else (lambda _e: set_(replace(action, mega=not action.mega))),
                tooltip="Mega Evolved on an earlier turn" if already else ("Mega Evolves this turn (click to undo)" if action.mega else "Mega Evolve this turn"),
                data={"mega": (where, i, slot), "on": action.mega},
            ))
        hits = (self.hits or {}).get((where, i, slot))
        lines: list[ft.Control] = []
        if action.kind == "move" and action.target in ("foe", "foes"):
            if self.hits is None:
                lines.append(_small("…", tooltip="Calculating"))
            elif not hits:
                info = ctx.catalogs.move_by_name(action.move)
                if info is not None and (info.category or "").lower() != "status":   # a status move does no damage anyway
                    lines.append(_small("No damage: immune, or no effect", color=Palette.WARNING))
            else:
                text = hit_text(hits, lambda j: ctx.names.opp(OppRef(j)))
                pins = [ft.PopupMenuItem(content=ft.Text(f"Pin vs {ctx.names.opp(OppRef(h.foe_index))} to Key calcs"), icon=ft.Icons.PUSH_PIN_OUTLINED,
                                         on_click=lambda _e, f=h.foe_index: self.actions.pin_hit(self.sc, (where, i, slot), f)) for h in hits]
                lines.append(ft.Row(spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                    ft.Container(content=_small(text, color=Palette.HIT_DEALT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS), expand=True, ink=True,
                                 tooltip="Open in Calc", on_click=lambda _e, f=hits[0].foe_index: self.actions.open_hit(self.sc, (where, i, slot), f),
                                 data={"hit": (where, i, slot)}),
                    ft.PopupMenuButton(icon=ft.Icons.PUSH_PIN_OUTLINED, icon_size=IconSize.SM, tooltip="Pin to Key calcs", items=pins),
                ]))
        return ft.Container(col=col, content=ft.Column(spacing=2, tight=True, controls=[
            ft.Row(spacing=Space.SM, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=row), *lines]),
            padding=Space.XS, border_radius=Radius.SM, bgcolor=Palette.SURFACE_2, data={"picker": (where, i, slot)})

    def _action_controls(self, where: Where, i: int, slot: int, action: Action, label: str, items: list, foes: Sequence[OppRef]) -> list[ft.Control]:
        out: list[ft.Control] = [ft.PopupMenuButton(tooltip="What it does this turn", content=_pill(label, on=bool(action.kind)), items=items,
                                                    data={"action": (where, i, slot)})]
        if action.kind == "move" and action.target == "foe":
            plan = self.ctx.plan
            order = [o.index for o in foes] + [j for j in range(len(plan.opponent)) if j not in {o.index for o in foes}]
            targets = [ft.PopupMenuItem(content=ft.Text(self._opp_name(j) + ("" if j in {o.index for o in foes} else " (not on the field)")),
                                        on_click=lambda _e, j=j: self._save(set_action(self.sc, where, i, slot,
                                                                                       replace(action, foe=OppRef(j, self._opp_species(j) or ""))))) for j in order]
            name = self._opp_name(action.foe.index) if action.foe is not None else "pick a target"
            out.append(ft.PopupMenuButton(tooltip="Target", content=_pill(f"→ {name}", on=action.foe is not None), items=targets, data={"target": (where, i, slot)}))
        elif action.kind == "move" and action.target in ("foes", "ally"):
            out.append(_small("→ both foes" if action.target == "foes" else "→ ally"))
        return out

    def _move_action(self, move: str, foes: Sequence[OppRef], mega: bool) -> Action:
        target = default_target(self.ctx.move_target(move))
        foe = None
        if target == "foe":
            foe = foes[0] if foes else (OppRef(0, self._opp_species(0) or "") if self.ctx.plan.opponent else None)
        return Action("move", move, target, foe, mega)

    # -- "If…" ------------------------------------------------------------------------------

    def _add_if(self, i: int) -> None:
        board = board_at(self.ctx.plan, self.sc, i + 1)
        first = board.left or board.right
        self.opened = True
        self._save(add_branch(self.sc, i + 1, ko=first))

    def _branch_block(self, b: int, br: Any) -> ft.Control:
        plan, names = self.ctx.plan, self.ctx.names
        after = min(br.after_turn, len(self.sc.turns))
        board = board_at(plan, self.sc, after)
        on_field = [r for r in (board.left, board.right) if r is not None]

        def options(refs: Sequence[MemberRef]) -> list[ft.DropdownOption]:
            return [ft.DropdownOption(key=r.box_entry_id, text=names.member(r)) for r in refs]

        if br.kind == "ko":
            ko = ft.Dropdown(value=br.ko.box_entry_id if br.ko else None, options=options(on_field), width=170, dense=True,
                             on_select=lambda e: self._save(set_branch(self.sc, b, ko=next((r for r in on_field if r.box_entry_id == e.control.value), None))))
            rep = ft.Dropdown(value=br.replacement.box_entry_id if br.replacement else None, options=options(board.bench), width=170, dense=True,
                              hint_text="nobody",
                              on_select=lambda e: self._save(set_branch(self.sc, b, replacement=next((r for r in board.bench if r.box_entry_id == e.control.value), None))))
            head: list[ft.Control] = [_small("If", color=Palette.ON_SURFACE), ko, _small(f"is KO'd after T{br.after_turn} → bring", color=Palette.ON_SURFACE), rep]
        else:
            head = [ft.TextField(value=br.text, label=f"If… (after T{br.after_turn})", hint_text="they set Trick Room, Kingambit is still up…", dense=True,
                                 text_size=13, width=380,   # a wrapping row: children keep their own width
                                 on_blur=lambda e: self._save(set_branch(self.sc, b, text=e.control.value or ""), redraw=False)
                                 if (e.control.value or "") != br.text else None)]
        head.append(ft.PopupMenuButton(icon=ft.Icons.MORE_HORIZ, icon_size=IconSize.SM, tooltip="“If…” actions", items=[
            ft.PopupMenuItem(content=ft.Text("One of yours is KO'd"), on_click=lambda _e: self._save(set_branch(self.sc, b, kind="ko"))),
            ft.PopupMenuItem(content=ft.Text("Something else (write it)"), on_click=lambda _e: self._save(set_branch(self.sc, b, kind="other"))),
            ft.PopupMenuItem(),
            ft.PopupMenuItem(content=ft.Text("Delete this “If…”"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda _e: self._save(remove_branch(self.sc, b))),
        ]))
        rows: list[ft.Control] = [ft.Row(spacing=Space.SM, wrap=True, run_spacing=Space.XS, vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Icon(ft.Icons.CALL_SPLIT, size=IconSize.SM, color=Accent.PLANS), *head])]
        rows += [self._turn_row(b, j, t) for j, t in enumerate(br.turns)]
        rows.append(ft.TextButton("Add turn", icon=ft.Icons.ADD, disabled=len(br.turns) >= MAX_BRANCH_TURNS,
                                  on_click=lambda _e: self._save(add_turn(self.sc, b))))
        return ft.Container(
            content=ft.Column(spacing=Space.XS, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=rows),
            margin=ft.Margin.only(left=Space.LG), padding=Space.SM, border_radius=Radius.SM, bgcolor=Palette.SURFACE_2,
            border=ft.Border.only(left=ft.BorderSide(3, alpha(Accent.PLANS, 0.6))), data={"branch": b},
        )

    # -- helpers ----------------------------------------------------------------------------

    def _their_field(self, where: Where, i: int) -> None:
        current = [o.index for o in self.sc.turns_of(where)[i].their_field]

        def pick(indices: tuple[int, ...]) -> None:
            field = tuple(OppRef(j, self._opp_species(j) or "") for j in indices)
            self._save(set_turn(self.sc, where, i, their_field=field))

        self.actions.pick_pair(f"Their field on T{self.sc.turn_number(where, i)}", current, True, pick)

    def _change_their_lead(self) -> None:
        def pick(indices: tuple[int, ...]) -> None:
            if indices:
                self._save(replace(self.sc, their_lead=tuple(OppRef(j, self._opp_species(j) or "") for j in indices)))
        self.actions.pick_pair("Their lead", [o.index for o in self.sc.their_lead], False, pick)

    def _save(self, sc: Scenario, *, redraw: bool = True) -> None:
        self.sc = sc
        self.actions.save(sc)
        if redraw:
            self.refresh()

    def _opp_species(self, index: int) -> str | None:
        opp = self.ctx.plan.opponent
        return opp[index].pokemon.species if 0 <= index < len(opp) else None

    def _opp_name(self, index: int) -> str:
        return self.ctx.names.opp(OppRef(index, self._opp_species(index) or ""))


class FlowSection(ft.Column):
    def __init__(self, *, actions: FlowActions) -> None:
        super().__init__(spacing=Space.SM, tight=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.actions = actions
        self.ctx: FlowContext | None = None
        self.scenarios: list[Scenario] = []
        self.cards: dict[str, ScenarioCard] = {}
        self._open: set[str] = set()
        self._hits: dict[str, dict[HitKey, tuple[Hit, ...]]] = {}
        self._fallback = ft.PopupMenuItem(content=ft.Text("Any other lead"), icon=ft.Icons.HELP_OUTLINE, on_click=lambda _e: self.actions.add(True))
        self.add_menu = ft.PopupMenuButton(
            tooltip="Plan for an opposing lead",
            content=ft.Row(spacing=Space.XS, tight=True, controls=[ft.Icon(ft.Icons.ADD, size=IconSize.SM, color=Accent.PLANS),
                                                                     ft.Text("Add", theme_style=ft.TextThemeStyle.LABEL_LARGE, color=Accent.PLANS)]),
            items=[ft.PopupMenuItem(content=ft.Text("If they lead…"), icon=ft.Icons.GROUPS_OUTLINED, on_click=lambda _e: self.actions.add(False)),
                   self._fallback],
        )

    def show(self, ctx: FlowContext, scenarios: Sequence[Scenario], *, keep_hits: bool = False) -> None:
        self.ctx = ctx
        self.scenarios = list(scenarios)
        if not keep_hits:
            self._hits = {}
        self._fallback.disabled = any(s.is_fallback for s in self.scenarios)
        self._render()

    def _render(self) -> None:
        if not self.scenarios:
            self.cards = {}
            self.controls = [_small("No scenarios yet. Add one for a lead they often bring (If they lead…), and one for any other lead.")]
        else:
            self.cards = {sc.scenario_id: self._card(sc) for sc in self.scenarios}
            self.controls = list(self.cards.values())
        if is_mounted(self):
            self.update()

    def _card(self, sc: Scenario) -> ScenarioCard:
        assert self.ctx is not None
        return ScenarioCard(sc, ctx=self.ctx, actions=self.actions, opened=sc.scenario_id in self._open,
                            hits=self._hits.get(sc.scenario_id), on_toggle=self.toggle)

    def toggle(self, scenario_id: str) -> None:
        self._open.symmetric_difference_update({scenario_id})
        card = self.cards.get(scenario_id)
        if card is not None:
            card.opened = scenario_id in self._open
            card.refresh()

    def open(self, scenario_id: str) -> None:
        self._open.add(scenario_id)

    def updated(self, sc: Scenario) -> None:
        """A scenario was saved: keep it, and drop its damage until it is recomputed."""
        self.scenarios = [sc if s.scenario_id == sc.scenario_id else s for s in self.scenarios]
        self._hits.pop(sc.scenario_id, None)
        card = self.cards.get(sc.scenario_id)
        if card is not None:
            card.sc, card.hits = sc, None

    def set_hits(self, scenario_id: str, hits: dict[HitKey, tuple[Hit, ...]]) -> None:
        self._hits[scenario_id] = hits
        card = self.cards.get(scenario_id)
        if card is not None:
            card.hits = hits
            if card.opened:
                card.refresh()


__all__ = ["FLOW_TIP", "FlowActions", "FlowContext", "FlowSection", "ScenarioCard"]
