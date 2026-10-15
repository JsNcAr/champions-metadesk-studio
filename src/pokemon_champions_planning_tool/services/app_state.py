"""Small key-value state kept in the database (``app_state``): when something last ran."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def check_due(session, key: str, hours: float = 24) -> bool:
    """True at most once per ``hours`` per key; records the check time when due."""
    from ..infrastructure.database.repositories import TournamentRepository

    repo = TournamentRepository(session)
    stamp = repo.get_state(key)
    now = datetime.now(timezone.utc)
    if stamp:
        try:
            last = datetime.fromisoformat(stamp)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < timedelta(hours=hours):
                return False
        except ValueError:
            pass
    repo.set_state(key, now.isoformat())
    return True


__all__ = ["check_due"]
