"""Internal box storage model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .pokemon import Pokemon


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class BoxEntry:
    """Represents one Pokemon stored in the user's box."""

    pokemon: Pokemon
    box_entry_id: UUID = field(default_factory=uuid4)
    notes: str = ""
    tags: list[str] = field(default_factory=list)
    is_favorite: bool = False
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)