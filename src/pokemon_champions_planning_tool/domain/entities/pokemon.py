"""Primary Pokemon entity populated from PokéAPI and user input."""

from pydantic import BaseModel, ConfigDict, Field, computed_field

from .pokemon_ability import PokemonAbility
from .pokemon_form import PokemonForm
from .pokemon_move import PokemonMove
from .pokemon_stats import PokemonStats


class Pokemon(BaseModel):
    """Represents a Pokemon species/form and its API-backed attributes."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: str = Field(
        ..., description="Stable PokéAPI identifier for the Pokemon or form."
    )
    display_name: str = Field(..., description="Human-readable name shown in the UI.")
    species_name: str | None = Field(
        default=None,
        description="Base species name when the record represents a specific form.",
    )
    form_name: str = Field(
        default="Base", description="Form label such as Base, Mega, or Regional."
    )
    dex_number: int | None = Field(
        default=None,
        ge=1,
        description="National Pokédex number when available.",
    )
    types: list[str] = Field(
        default_factory=list,
        description="Primary and secondary Pokemon types.",
    )
    sprite_url: str | None = Field(
        default=None, description="Default sprite or artwork URL for the Pokemon."
    )
    stats: PokemonStats = Field(..., description="Validated stat block for the Pokemon.")
    abilities: list[PokemonAbility] = Field(
        default_factory=list,
        description="Known abilities for this Pokemon or form.",
    )
    moves: list[PokemonMove] = Field(
        default_factory=list,
        description="Known or selected moves associated with the Pokemon.",
    )
    available_forms: list[PokemonForm] = Field(
        default_factory=list,
        description="Other forms that can be selected for this Pokemon.",
    )

    @computed_field(return_type=int)
    @property
    def is_stub(self) -> bool:
        """True for a placeholder written without PokéAPI data (no types, no stats)."""
        return not self.types and self.stats.total == 0

    @property
    def total(self) -> int:
        """Expose the derived stat total for convenience."""

        return self.stats.total

