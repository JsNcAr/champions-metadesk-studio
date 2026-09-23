"""Per-Pokémon matchups (abilities included), item usage per species and the item picker's
"Popular" section."""

import unittest
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.type_chart import (
    bucket_profile,
    defensive_profile_with_ability,
    team_matrix_from_profiles,
    team_weakness_from_profiles,
)
from pokemon_champions_planning_tool.infrastructure.database.models import (
    ItemRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository
from pokemon_champions_planning_tool.services.tournament_service import TournamentService
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.move_options import invalidate_move_usage, item_usage_for
from pokemon_champions_planning_tool.ui.views.team.dialogs.item_picker import ItemPickerDialog

from _ui_stubs import check_layout, serialise


class TestAbilityMatchups(unittest.TestCase):
    def test_types_alone(self):
        profile, notes = defensive_profile_with_ability(["rock", "dark"], "Sand Stream")
        buckets = bucket_profile(profile)
        self.assertEqual(buckets[4.0], ["fighting"])
        self.assertIn("psychic", buckets[0.0])
        self.assertEqual(notes, [])

    def test_abilities_change_the_profile(self):
        levitate, notes = defensive_profile_with_ability(["ghost", "poison"], "Levitate")
        self.assertEqual(levitate["ground"], 0.0)
        self.assertEqual(notes, ["Levitate: immune to Ground"])
        fat, _ = defensive_profile_with_ability(["normal"], "Thick Fat")
        self.assertEqual((fat["fire"], fat["ice"]), (0.5, 0.5))
        fluffy, notes = defensive_profile_with_ability(["normal"], "fluffy")
        self.assertEqual(fluffy["fire"], 2.0)
        self.assertIn("double Fire", notes[0])
        baked, notes = defensive_profile_with_ability(["fire", "dark"], "Well-Baked Body")
        self.assertEqual(baked["fire"], 0.0)
        self.assertEqual(notes, ["Well-Baked Body: immune to Fire"], "the ability name as written")

    def test_team_grid_counts_abilities(self):
        levitate, _ = defensive_profile_with_ability(["ghost", "poison"], "Levitate")
        plain, _ = defensive_profile_with_ability(["ghost", "poison"], "Cursed Body")
        weak, _resist, immune = team_weakness_from_profiles([levitate, plain, None])["ground"]
        self.assertEqual((weak, immune), (1, 1))
        self.assertEqual(team_matrix_from_profiles([levitate, None])["ground"], [0.0, 1.0], "an empty slot reads neutral")


class TestItemUsage(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.sf = lambda: Session(self.engine)
        with self.sf() as s:
            repo = TournamentRepository(s)
            repo.upsert_tournament(TournamentRecord(tournament_id="t1", name="Regional", event_date=datetime.now(timezone.utc),
                                                   format_regulation="Regulation M-C", game_platform="Pokémon Champions"))
            for i, (cid, item) in enumerate([("charizard", "Choice Specs"), ("charizard", "Choice Specs"), ("charizard-mega-y", "Charizardite Y"),
                                             ("charizard", None), ("incineroar", "Sitrus Berry")]):
                team = TournamentTeamRecord(tournament_id="t1", player_name=f"P{i}", placement=i + 1, showdown_text="")
                repo.save_team(team, [TournamentTeamMemberRecord(slot_position=1, canonical_id=cid, species_name=cid, item=item)])
            s.add(ItemRecord(canonical_id="choice-specs", display_name="Choice Specs", category="choice", is_champions_legal=True))
            s.add(ItemRecord(canonical_id="charizardite-y", display_name="Charizardite Y", category="mega-stone", is_champions_legal=True,
                             target_species="charizard", target_form="mega-y"))
            s.add(ItemRecord(canonical_id="life-orb", display_name="Life Orb", category="held", is_champions_legal=True))
            s.commit()
        invalidate_move_usage()
        self.addCleanup(invalidate_move_usage)

    def test_usage_counts_megas_for_their_base(self):
        with self.sf() as s:
            counts = TournamentRepository(s).item_usage("charizard")
            shares = TournamentService(s).item_usage("charizard")
        self.assertEqual(counts, [("Choice Specs", 2), ("Charizardite Y", 1)])
        self.assertEqual(round(shares["Choice Specs"], 2), 0.5, "2 of the 4 Charizard rosters")

    def test_usage_by_catalogue_id_and_the_picker(self):
        catalogs = Catalogs.load(self.sf)
        usage = item_usage_for(catalogs, "charizard-mega-y", self.sf)
        self.assertEqual(set(usage), {"choice-specs", "charizardite-y"})
        picker = ItemPickerDialog(catalogs=catalogs, species_name="charizard", current_item_id=None, on_pick=lambda _i: None, on_close=lambda: None)
        picker.set_usage(usage)
        self.assertEqual(picker._list.controls[0].value, "Popular for Charizard")
        first = picker._list.controls[1]
        self.assertIn("Choice Specs", str(first.content.controls[1].controls[0].value))
        check_layout(picker)
        serialise(picker)
        picked = []
        picker._on_pick = picked.append
        picker._pick_first()
        self.assertEqual(picked, ["choice-specs"], "Enter takes the most popular")
        picker.set_sort("name")
        self.assertNotIn("Popular for Charizard", [getattr(r, "value", None) for r in picker._list.controls])


if __name__ == "__main__":
    unittest.main()
