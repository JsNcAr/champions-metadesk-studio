"""Pure domain entity representing a held item or Mega Stone."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Item(BaseModel):
    """Represents a Pokémon held item with all metadata needed by the planner."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: str = Field(
        ..., description="Stable slug identifier, e.g. 'choice-scarf' or 'charizardite-x'."
    )
    display_name: str = Field(
        ..., description="Human-readable name shown in the UI, e.g. 'Choice Scarf'."
    )
    category: str = Field(
        default="other",
        description="Functional category: 'mega_stone', 'choice', 'held-items', 'other', etc.",
    )
    is_champions_legal: bool = Field(
        default=True,
        description="Whether this item is available in the Pokémon Champions format.",
    )
    sprite_url: str | None = Field(
        default=None, description="URL to the item sprite from PokéAPI."
    )
    short_effect: str = Field(
        default="", description="Concise English effect description from PokéAPI."
    )
    # Mega Stone specific fields
    target_species: str | None = Field(
        default=None,
        description="Species slug for Mega Stones, e.g. 'charizard'. Null for non-Mega items.",
    )
    target_form: str | None = Field(
        default=None,
        description="Target Mega form slug, e.g. 'mega-x', 'mega-y', 'mega'. Null for non-Mega items.",
    )
    # Stat modifier fields
    stat_modifiers: dict[str, float] = Field(
        default_factory=dict,
        description="Stat multipliers applied when held, e.g. {'speed': 1.5} for Choice Scarf.",
    )
