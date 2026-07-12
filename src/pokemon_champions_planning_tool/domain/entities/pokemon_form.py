"""Validated Pokemon form model populated from PokéAPI."""

from pydantic import BaseModel, ConfigDict, Field


class PokemonForm(BaseModel):
    """Represents an alternate form or variant of a Pokemon."""

    model_config = ConfigDict(extra="forbid")

    form_id: str = Field(..., description="Stable identifier for the form.")
    display_name: str = Field(..., description="Human-readable form name.")
    is_mega: bool = Field(default=False, description="Whether the form is a Mega form.")
    is_regional: bool = Field(
        default=False, description="Whether the form is a regional variant."
    )
    sprite_url: str | None = Field(
        default=None, description="Sprite or artwork URL for the form."
    )
    type_override: list[str] = Field(
        default_factory=list,
        description="Types that should override the base Pokemon types.",
    )