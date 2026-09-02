"""TeamStore: one-session load, guardrails across slots, mega-stone auto-form, spreads,
totals/health/coverage, swap, export."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_ability import PokemonAbility
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import ItemRecord, MegaEvolutionRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.views.team import TeamStore


def _mon(cid, name, types, abilities=("blaze",), **stats) -> Pokemon:
    base = dict(hp=80, attack=80, defense=80, sp_atk=80, sp_def=80, speed=80)
    base.update(stats)
    return Pokemon(canonical_id=cid, display_name=name, species_name=cid, types=list(types),
                   stats=PokemonStats(**base), abilities=[PokemonAbility(name=a) for a in abilities])


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'team.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


class _TeamStoreCase(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        with self.db.session() as s:
            repo = BoxRepository(s)
            self.charizard = repo.upsert_box_entry(BoxEntry(pokemon=_mon("charizard", "Charizard", ["fire", "flying"], ("blaze", "solar-power"), attack=84, speed=100))).box_entry_id
            self.lucario = repo.upsert_box_entry(BoxEntry(pokemon=_mon("lucario", "Lucario", ["fighting", "steel"], attack=110))).box_entry_id
            self.ghost = repo.create_planned_entry(BoxEntry(pokemon=_mon("gengar", "Gengar", ["ghost", "poison"]), is_planned=True)).box_entry_id
            s.add(MegaEvolutionRecord(canonical_id="charizard-mega-x", species_name="charizard", display_name="Mega Charizard X", types=["fire", "dragon"],
                                      hp=78, attack=130, defense=111, special_attack=130, special_defense=85, speed=100))
            s.add(MegaEvolutionRecord(canonical_id="charizard-mega-y", species_name="charizard", display_name="Mega Charizard Y", types=["fire", "flying"],
                                      hp=78, attack=104, defense=78, special_attack=159, special_defense=115, speed=100))
            s.add(MegaEvolutionRecord(canonical_id="lucario-mega", species_name="lucario", display_name="Mega Lucario", types=["fighting", "steel"],
                                      hp=70, attack=145, defense=88, special_attack=140, special_defense=70, speed=112))
            s.add(ItemRecord(canonical_id="charizardite-x", display_name="Charizardite X", category="mega-stone", is_champions_legal=True, target_species="charizard", target_form="mega-x", stat_modifiers={}))
            s.add(ItemRecord(canonical_id="lucarionite", display_name="Lucarionite", category="mega-stone", is_champions_legal=True, target_species="lucario", target_form="mega", stat_modifiers={}))
            s.add(ItemRecord(canonical_id="choice-band", display_name="Choice Band", category="choice", is_champions_legal=True, stat_modifiers={"attack": 1.5}))
            s.commit()
        self.catalogs = Catalogs.load(self.db.session)
        self.store = TeamStore(self.catalogs, self.db.session)
        self.changes = []
        self.store.subscribe(self.changes.append)

    def tearDown(self):
        self.db.close()


class TestTeamStore(_TeamStoreCase):
    def test_empty_database_loads_cleanly(self):
        self.store.load()
        self.assertEqual(self.store.teams, [])
        self.assertIsNone(self.store.active_team_id)
        self.assertEqual([s.filled for s in self.store.slots], [False] * 6)
        self.assertEqual(self.store.summary.filled, 0)

    def test_create_assign_and_derived_slot_data(self):
        self.store.create_team("Sun")
        self.assertEqual([t.name for t in self.store.teams], ["Sun"])
        self.store.assign(1, self.charizard)
        slot = self.store.slot(1)
        self.assertTrue(slot.filled)
        self.assertEqual(slot.member.ability, "Blaze", "first ability is the default")
        self.assertEqual([f.label for f in slot.form_choices()], ["Base", "Mega Charizard X", "Mega Charizard Y"])
        self.assertEqual(slot.ability_options, ["Blaze", "Solar Power"])
        self.assertEqual(slot.battle_stats.attack, 104, "level 50, 0 EVs, 31 IVs, neutral: floor((2·84+31)·50/100)+5")
        self.assertEqual(self.store.summary.filled, 1)
        self.assertIn(("slot", 1), self.changes)
        self.assertIn(("summary",), self.changes)

    def test_mega_stone_switches_form_and_choice_band_boosts(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.set_item(1, "charizardite-x")
        slot = self.store.slot(1)
        self.assertEqual(slot.member.selected_form, "charizard-mega-x", "stone's target_form maps to the mega canonical id")
        self.assertEqual(slot.form.label, "Mega Charizard X")
        self.assertEqual(slot.validation.unlocked_form, "mega-x")
        self.assertTrue(slot.validation.is_valid)
        self.store.set_item(1, "choice-band")
        self.assertEqual(self.store.slot(1).member.selected_form, "base", "non-stone item drops the mega form")
        self.assertEqual(self.store.slot(1).effective_stats.attack, 126, "84 × 1.5")
        self.store.set_item(1, None)
        self.assertIsNone(self.store.slot(1).item)

    def test_cross_slot_guardrail_flags_second_mega_stone(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        self.store.set_item(1, "charizardite-x")
        self.store.set_item(2, "lucarionite")
        s2 = self.store.slot(2)
        self.assertIsNotNone(s2.validation.warning, "the check the legacy UI disabled with `if False`")
        self.assertEqual(self.store.summary.mega_stones, 2)
        self.assertTrue(any(c.status == "warn" and "Mega Stones" in c.label for c in self.store.summary.checks))

    def test_duplicate_items_and_planned_in_health(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        self.store.assign(3, self.ghost)
        self.store.set_item(1, "choice-band")
        self.store.set_item(2, "choice-band")
        checks = {c.label: c for c in self.store.summary.checks}
        self.assertIn("Duplicate items", checks)
        self.assertEqual(self.store.summary.planned, 1)
        self.assertIn("1 planned", checks)
        self.assertEqual(checks["3/6"].status, "info")

    def test_totals_and_coverage(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        summary = self.store.summary
        self.assertEqual(summary.totals.attack, 84 + 110)
        self.assertEqual(summary.averages.attack, round((84 + 110) / 2))
        self.assertEqual(summary.weakness["rock"], (1, 1, 0), "Charizard 4× weak, Lucario resists")
        self.assertEqual(summary.matrix["ground"][:2], [0.0, 2.0])

    def test_spread_validation_and_save(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        problems = self.store.save_spread(1, nature="Timid", points={"speed": 32, "special_attack": 32, "hp": 3})
        self.assertTrue(problems and "exceeds 66" in problems[0])
        self.assertTrue(self.store.save_spread(1, nature="Timid", points={"speed": 33}))
        self.assertEqual(self.store.save_spread(1, nature="Timid", points={"speed": 32, "special_attack": 32, "hp": 2, "attack": 0}), [])
        slot = self.store.slot(1)
        self.assertEqual(slot.member.points, {"speed": 32, "special_attack": 32, "hp": 2})
        self.assertEqual(slot.battle_stats.speed, 167, "100 base, 32 points, Timid: floor((100+32+20)·1.1)")
        self.assertEqual(slot.battle_stats.hp, slot.base_stats.hp + 2 + 75)
        self.assertEqual(slot.spread_summary, "Timid · 2 HP / 32 SpA / 32 Spe")
        self.assertEqual((slot.points_used, slot.points_left), (66, 0))
        labels = [c.label for c in self.store.summary.checks]
        self.assertIn("Spreads complete", labels)
        self.store.assign(2, self.lucario)
        labels = [c.label for c in self.store.summary.checks]
        self.assertIn("1 unspread", labels)
        self.store.save_spread(2, nature="Jolly", points={"attack": 32, "speed": 30})
        labels = [c.label for c in self.store.summary.checks]
        self.assertIn("4 points unused", labels)
        self.assertEqual(self.store.slot(2).spread_summary, "Jolly · 32 Atk / 30 Spe")

    def test_moves_tera_notes_and_export(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.set_move(1, 0, "Heat Wave")
        self.store.set_move(1, 3, "Protect")
        self.store.set_move(1, 0, "")
        self.assertEqual([m.name for m in self.store.slot(1).member.moveset], ["Protect"])
        self.store.set_tera(1, "Grass")
        self.store.set_notes(1, "  lead  ")
        member = self.store.slot(1).member
        self.assertEqual((member.tera_type, member.notes), ("grass", "lead"))
        text = self.store.export_text()
        self.assertIn("Charizard", text)
        self.assertIn("Tera Type: Grass", text)

    def test_clear_restore_swap_rename_delete(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)
        removed = self.store.clear_slot(1)
        self.assertEqual(removed.box_entry_id, self.charizard)
        self.assertFalse(self.store.slot(1).filled)
        self.store.restore_slot(removed)
        self.assertTrue(self.store.slot(1).filled)
        self.assertTrue(self.store.swap(1, 6))
        self.assertFalse(self.store.slot(1).filled)
        self.assertEqual(self.store.slot(6).entry.pokemon.display_name, "Charizard")
        self.store.rename_team("Sun v2")
        self.assertEqual(self.store.active_team_name, "Sun v2")
        with self.assertRaises(ValueError):
            self.store.create_team("Sun v2")
        self.assertEqual(self.store.delete_team(), "Sun v2")
        self.assertEqual(self.store.teams, [])

    def test_box_choices_and_assigned_ids(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.assertEqual({e.pokemon.display_name for e in self.store.box_choices()}, {"Charizard", "Lucario", "Gengar"})
        self.assertEqual({e.pokemon.display_name for e in self.store.box_choices(include_planned=False)}, {"Charizard", "Lucario"})
        self.assertEqual(self.store.assigned_entry_ids(), {self.charizard})


if __name__ == "__main__":
    unittest.main()


class TestTeamStoreExtras(_TeamStoreCase):
    def test_duplicate_team_copies_slots(self):
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.set_item(1, "charizardite-x")
        self.store.save_spread(1, nature="Adamant", points={"attack": 32})
        new_id = self.store.duplicate_team("Sun copy")
        self.assertEqual(self.store.active_team_id, new_id)
        self.assertEqual([t.name for t in self.store.teams], ["Sun", "Sun copy"])
        slot = self.store.slot(1)
        self.assertEqual(slot.member.selected_form, "charizard-mega-x")
        self.assertEqual(slot.member.points, {"attack": 32})
        self.assertEqual(slot.member.nature, "Adamant")
