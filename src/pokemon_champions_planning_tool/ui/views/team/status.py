"""How a health check looks: the tone and icon shared by the header, the panel and Compare."""

from __future__ import annotations

import flet as ft

from ...components import StatusChip
from .summary import HealthCheck

STATUS_TONE = {"ok": "success", "warn": "warning", "error": "error", "info": "info"}
STATUS_ICON = {"ok": ft.Icons.CHECK, "warn": ft.Icons.WARNING_AMBER_OUTLINED, "error": ft.Icons.ERROR_OUTLINE, "info": ft.Icons.INFO_OUTLINE}


def check_chip(check: HealthCheck, *, tooltip: bool = True) -> StatusChip:
    return StatusChip(check.label, STATUS_TONE.get(check.status, "neutral"), icon=STATUS_ICON.get(check.status), tooltip=check.detail if tooltip else None)  # type: ignore[arg-type]


def health_summary(checks) -> tuple[str, str]:
    """One line for the whole team: ("2 warnings · 1 note", tone), or ("All good", "success")."""
    errors = sum(1 for c in checks if c.status == "error")
    warns = sum(1 for c in checks if c.status == "warn")
    infos = sum(1 for c in checks if c.status == "info")
    parts = []
    if errors:
        parts.append(f"{errors} problem{'s' if errors != 1 else ''}")
    if warns:
        parts.append(f"{warns} warning{'s' if warns != 1 else ''}")
    if infos:
        parts.append(f"{infos} note{'s' if infos != 1 else ''}")
    if not parts:
        return "All good", "success"
    return " · ".join(parts), "error" if errors else ("warning" if warns else "info")


__all__ = ["STATUS_ICON", "STATUS_TONE", "check_chip", "health_summary"]
