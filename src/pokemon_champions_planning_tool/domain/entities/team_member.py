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
    # Champions spread: stat points per stat (0–32 each, 66 total); only invested stats present.
    # Level is fixed at 50 and IVs at 31, so there is nothing else to store.
    points: dict[str, int] = field(default_factory=dict)
    nature: str | None = None
    level: int = 50
    # Terastallization type (lowercase type name) or None when unset.
    tera_type: str | None = None
