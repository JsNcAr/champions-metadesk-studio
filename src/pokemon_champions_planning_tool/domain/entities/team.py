"""Internal team aggregate model."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from .team_member import TeamMember


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Team:
    """Represents a named team with assigned members."""

    name: str
    team_id: UUID = field(default_factory=uuid4)
    description: str = ""
    format_id: str | None = None        # None: the team follows the default format (Settings)
    members: list[TeamMember] = field(default_factory=list)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)