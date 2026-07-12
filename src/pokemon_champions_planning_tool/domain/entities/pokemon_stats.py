"""Validated Pokemon stat model populated from PokéAPI."""

from pydantic import BaseModel, ConfigDict, Field, computed_field


class PokemonStats(BaseModel):
    """Represents the base stat block for a Pokemon."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    hp: int = Field(..., ge=0, description="HP stat.")
    attack: int = Field(..., ge=0, description="Attack stat.")
    defense: int = Field(..., ge=0, description="Defense stat.")
    special_attack: int = Field(
        ..., alias="sp_atk", ge=0, description="Special Attack stat."
    )
    special_defense: int = Field(
        ..., alias="sp_def", ge=0, description="Special Defense stat."
    )
    speed: int = Field(..., ge=0, description="Speed stat.")

    @computed_field(return_type=int)
    @property
    def total(self) -> int:
        """Compute the total base stats."""

        return (
            self.hp
            + self.attack
            + self.defense
            + self.special_attack
            + self.special_defense
            + self.speed
        )