"""Validated Pokemon move model populated from PokéAPI or user selection."""

from pydantic import BaseModel, ConfigDict, Field


class PokemonMove(BaseModel):
    """Represents a Pokemon move with combat metadata."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., description="Move name.")
    type: str | None = Field(default=None, description="Move type.")
    power: int | None = Field(default=None, ge=0, description="Base power.")
    accuracy: int | None = Field(default=None, ge=0, description="Accuracy percentage.")
    category: str | None = Field(default=None, description="Physical, special, or status.")
    priority: int = Field(default=0, description="Move priority.")
    learn_method: str | None = Field(
        default=None, description="How the move is learned, if known."
    )
    level_learned_at: int | None = Field(
        default=None, ge=0, description="Level at which the move is learned."
    )