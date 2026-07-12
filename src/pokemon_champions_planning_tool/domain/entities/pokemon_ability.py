"""Validated Pokemon ability model populated from PokéAPI."""

from pydantic import BaseModel, ConfigDict, Field


class PokemonAbility(BaseModel):
    """Represents one ability entry returned by the API."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Ability name.")
    slot: int | None = Field(default=None, ge=1, description="Ability slot number.")
    is_hidden: bool = Field(default=False, description="Whether the ability is hidden.")
    url: str | None = Field(default=None, description="API URL for the ability.")