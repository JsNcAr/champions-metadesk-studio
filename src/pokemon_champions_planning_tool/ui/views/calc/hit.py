"""One line per matchup, shared by the team strips, the rival cards and the team grid:
"Knock Off 57.6–68.3% (guaranteed 2HKO)", and the tooltip that explains a rating."""

from __future__ import annotations

from .classes import CLASS_HELP
from .state import SWEEP_CLASSES, MoveResult, TeamRating


def hit_text(result: MoveResult | None, fallback: str = "no damaging move", *, ko: bool = False) -> str:
    if result is None:
        return fallback
    text = f"{result.name} {result.min_pct:g}–{result.max_pct:g}%"
    return f"{text} ({result.ko_text})" if ko and result.ko_text else text


def speed_line(rating: TeamRating) -> str:
    if rating.your_speed == rating.their_speed:
        return f"Speed tie ({rating.your_speed})"
    return f"{'You move' if rating.faster else 'They move'} first ({rating.your_speed} vs {rating.their_speed})"


def rating_tooltip(rating: TeamRating, rival_name: str, hint: str = "") -> str:
    label = dict(SWEEP_CLASSES).get(rating.klass, rating.klass)
    head = f"vs {rival_name}: {label}" if rival_name else label
    return "\n".join(x for x in (
        f"{hint} · {head}" if hint else head,
        f"You: {hit_text(rating.your_best, ko=True)}",
        f"Them: {hit_text(rating.their_best, ko=True)}",
        speed_line(rating),
    ) if x)


def rating_legend(subject: str) -> str:
    return "\n".join([subject] + [f"{label}: {CLASS_HELP[key]}" for key, label in SWEEP_CLASSES])


__all__ = ["hit_text", "rating_legend", "rating_tooltip", "speed_line"]
