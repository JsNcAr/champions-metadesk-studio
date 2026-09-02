"""Tournament tier: official Play! Pokémon events by classification, or community.

Official events reach the app from Victory Road under the "Play! Pokémon Premier Events"
organizer (and the bundled seed under "Official VGC"). Everything from Limitless is run by
the community, however grand the name — "Broome Regional" and "Road to WORLDS" are fan
events — so the tier is decided by the organizer first and the event name second.
"""

from __future__ import annotations

TIER_WORLDS = "worlds"
TIER_INTERNATIONAL = "international"
TIER_REGIONAL = "regional"
TIER_SPECIAL = "special"
TIER_COMMUNITY = "community"

OFFICIAL_TIERS: tuple[str, ...] = (TIER_WORLDS, TIER_INTERNATIONAL, TIER_REGIONAL, TIER_SPECIAL)
ALL_TIERS: tuple[str, ...] = OFFICIAL_TIERS + (TIER_COMMUNITY,)

TIER_LABELS: dict[str, str] = {
    TIER_WORLDS: "Worlds",
    TIER_INTERNATIONAL: "Internationals",
    TIER_REGIONAL: "Regionals",
    TIER_SPECIAL: "Special Events",
    TIER_COMMUNITY: "Community",
}

# Singular, for a chip on one event.
TIER_EVENT_LABELS: dict[str, str] = {
    TIER_WORLDS: "Worlds",
    TIER_INTERNATIONAL: "International",
    TIER_REGIONAL: "Regional",
    TIER_SPECIAL: "Special Event",
    TIER_COMMUNITY: "Community",
}

_OFFICIAL_ORGANIZERS = frozenset(
    {
        "play! pokémon premier events",
        "play! pokemon premier events",
        "play! pokémon",
        "play! pokemon",
        "the pokémon company international",
        "the pokemon company international",
        "official vgc",
    }
)


def is_official_organizer(organizer: str | None) -> bool:
    return (organizer or "").strip().lower() in _OFFICIAL_ORGANIZERS


def is_official_tier(tier: str | None) -> bool:
    return tier in OFFICIAL_TIERS


def classify_event_tier(name: str | None, organizer: str | None) -> str:
    """Tier for an event. Community unless the organizer is official."""
    if not is_official_organizer(organizer):
        return TIER_COMMUNITY
    lowered = (name or "").lower()
    if "world" in lowered:
        return TIER_WORLDS
    if "international" in lowered:
        return TIER_INTERNATIONAL
    if "regional" in lowered:
        return TIER_REGIONAL
    return TIER_SPECIAL


def tiers_for_filter(source: str, tier: str) -> tuple[str, ...] | None:
    """Tiers to keep for a (source, tier) filter pair; None means no restriction."""
    if tier in OFFICIAL_TIERS:
        return (tier,)
    if source == "official":
        return OFFICIAL_TIERS
    if source == "community":
        return (TIER_COMMUNITY,)
    return None


__all__ = [
    "ALL_TIERS", "OFFICIAL_TIERS", "TIER_COMMUNITY", "TIER_EVENT_LABELS", "TIER_INTERNATIONAL", "TIER_LABELS",
    "TIER_REGIONAL", "TIER_SPECIAL", "TIER_WORLDS", "classify_event_tier", "is_official_organizer",
    "is_official_tier", "tiers_for_filter",
]
