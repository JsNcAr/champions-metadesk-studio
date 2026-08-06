"""Internal team assignment model."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from .pokemon_move import PokemonMove


@dataclass(slots=True)
class TeamMember:
    """Represents one box entry assigned to a team slot."""

    box_entry_id: UUID
    slot_position: int
    team_member_id: UUID = field(default_factory=uuid4)
    selected_form: str = "base"
    item: str | None = None
    moveset: list[PokemonMove] = field(default_factory=list)
    ability: str | None = None
    notes: str = ""