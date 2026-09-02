"""Official/community classification of tournaments."""

import unittest

from pokemon_champions_planning_tool.domain.event_tier import (
    OFFICIAL_TIERS,
    TIER_COMMUNITY,
    TIER_INTERNATIONAL,
    TIER_REGIONAL,
    TIER_SPECIAL,
    TIER_WORLDS,
    classify_event_tier,
    tiers_for_filter,
)

OFFICIAL = "Play! Pokémon Premier Events"


class TestClassify(unittest.TestCase):
    def test_official_events_by_name(self):
        self.assertEqual(classify_event_tier("2025 World Championships", OFFICIAL), TIER_WORLDS)
        self.assertEqual(classify_event_tier("2026 Europe International Championships", OFFICIAL), TIER_INTERNATIONAL)
        self.assertEqual(classify_event_tier("Bologna Regional Championships", OFFICIAL), TIER_REGIONAL)
        self.assertEqual(classify_event_tier("Pokémon Champions Special Event Tokyo", OFFICIAL), TIER_SPECIAL)
        self.assertEqual(classify_event_tier("2025 NAIC", "official vgc"), TIER_SPECIAL, "seed organizer counts as official")

    def test_community_events_keep_their_grand_names(self):
        for name in ('VGC UU "Broome Regional"', "Torneo KURAMI Road to WORLDS", "Trinity Championship 10", "Synchronized Worlds #2"):
            self.assertEqual(classify_event_tier(name, "Limitless Community"), TIER_COMMUNITY, name)
        self.assertEqual(classify_event_tier("2025 World Championships", None), TIER_COMMUNITY)

    def test_filter_tiers(self):
        self.assertIsNone(tiers_for_filter("All", "All"))
        self.assertEqual(tiers_for_filter("official", "All"), OFFICIAL_TIERS)
        self.assertEqual(tiers_for_filter("community", "All"), (TIER_COMMUNITY,))
        self.assertEqual(tiers_for_filter("official", TIER_WORLDS), (TIER_WORLDS,))
        self.assertEqual(tiers_for_filter("All", TIER_REGIONAL), (TIER_REGIONAL,), "a tier implies official")


if __name__ == "__main__":
    unittest.main()
