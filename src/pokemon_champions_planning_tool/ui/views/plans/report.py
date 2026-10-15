"""Markdown for matchup plans, shaped like a team report's matchup section. Pure.

Names are resolved by the caller (the store knows the catalogue and the team), so these
functions only lay text out and can be tested on plain strings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ....domain.stat_calc import format_points
from ..calc.state import PokemonState
from .model import Plan

_BULLETS = ("- ", "* ", "• ", "+ ")


@dataclass(frozen=True)
class PinLine:
    label: str
    line: str           # the calc line(s), "252+ Atk Kingambit Low Kick vs. … — guaranteed OHKO"; one per line
    note: str = ""


@dataclass(frozen=True)
class PlanText:
    """One plan with every name already resolved."""

    plan: Plan
    lead: tuple[str, ...] = ()
    back: tuple[str, ...] = ()
    opponent: tuple[str, ...] = ()           # one line per opposing Pokémon, "Kingambit @ Black Glasses"
    threats: tuple[tuple[str, str], ...] = ()   # (name, note) for each opponent with a note
    pins: tuple[PinLine, ...] = ()
    flow: tuple[str, ...] = ()                  # the battle flow, already laid out (flow.scenario_markdown)


def _bullets(text: str) -> list[str]:
    """The game plan, one Markdown bullet per line; indented lines become sub-bullets."""
    out: list[str] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = "  " if raw[:1] in (" ", "\t") else ""
        line = raw.strip()
        for marker in _BULLETS:
            if line.startswith(marker):
                line = line[len(marker):].strip()
                break
        out.append(f"{indent}- {line}")
    return out


def plan_markdown(text: PlanText, *, level: int = 2) -> str:
    plan = text.plan
    h = "#" * level
    lines = [f"{h} {plan.name}"]
    meta: list[str] = []
    if plan.difficulty:
        meta.append(f"**Difficulty:** {plan.difficulty_label}")
    if text.lead:
        meta.append(f"**Lead:** {' + '.join(text.lead)}")
    if text.back:
        meta.append(f"**Back:** {' + '.join(text.back)}")
    if meta:
        lines += ["", "  \n".join(meta)]
    if text.opponent:
        lines += ["", f"**Their team:** {' · '.join(text.opponent)}"]
    plan_bullets = _bullets(plan.game_plan)
    if plan_bullets:
        lines += ["", f"{h}# Game plan", "", *plan_bullets]
    if text.flow:
        lines += ["", f"{h}# Battle flow", "", *text.flow]
    if text.threats:
        lines += ["", f"{h}# Threats", ""]
        for name, note in text.threats:
            note_lines = [n.strip() for n in note.splitlines() if n.strip()]
            lines.append(f"- **{name}:** {' '.join(note_lines)}")
    if text.pins:
        lines += ["", f"{h}# Key calcs", ""]
        for pin in text.pins:
            head = f"*{pin.label}:* " if pin.label else ""
            tail = f" — {pin.note.strip()}" if pin.note.strip() else ""
            first, *more = pin.line.splitlines() or [""]
            lines.append(f"- {head}{first}{tail}")
            lines += [f"  - {extra}" for extra in more]   # a best-each-way pin: their hit under yours
    return "\n".join(lines) + "\n"


def pokemon_to_showdown(pokemon: PokemonState, name: str) -> str:
    """One calculator set as a Showdown paste block (for "Edit as paste…")."""
    lines = [f"{name} @ {pokemon.item}" if pokemon.item else name]
    if pokemon.ability:
        lines.append(f"Ability: {pokemon.ability}")
    points = format_points(pokemon.points)
    if points:
        lines.append(f"EVs: {points}")
    if pokemon.nature and pokemon.nature.lower() != "hardy":
        lines.append(f"{pokemon.nature.strip().title()} Nature")
    lines += [f"- {m}" for m in pokemon.moves if m]
    return "\n".join(lines)


def team_markdown(team_name: str, plans: Sequence[PlanText]) -> str:
    head = f"# {team_name} — matchup plans\n" if team_name else "# Matchup plans\n"
    if not plans:
        return head + "\n_No plans yet._\n"
    return head + "\n" + "\n".join(plan_markdown(p) for p in plans)


__all__ = ["PinLine", "PlanText", "plan_markdown", "pokemon_to_showdown", "team_markdown"]
