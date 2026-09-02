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
    points: dict[str, int] = field(default_factory=dict)
    nature: str | None = None
    # Legacy mainline spread fields — converted into ``points`` by the database backfill and
    # kept only until the builder stops writing them.
    evs: dict[str, int] = field(default_factory=dict)
    ivs: dict[str, int] = field(default_factory=dict)
    level: int = 50   # fixed at 50 in Champions
    # Terastallization type (lowercase type name) or None when unset.
    tera_type: str | None = None
