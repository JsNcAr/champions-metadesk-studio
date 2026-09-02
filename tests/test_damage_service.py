"""Damage calc service: builders from team slots, roster members and species; matchups."""

import unittest
from types import SimpleNamespace

from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.moves import MoveInfo, MoveMechanics
from pokemon_champions_planning_tool.domain.species import SpeciesInfo
from pokemon_champions_planning_tool.services.damage_calc_service import (
    build_calc_move,
    build_from_roster_member,
    build_from_slot,
    calc_stat_table,
    default_field,
    matchup,
    pokemon_from_species,
    slot_vs_slot,
)


def species(canonical_id, name, types, stats, abilities, weight=50.0, is_mega=False):
    return SpeciesInfo(canonical_id=canonical_id, showdown_id=name.lower().replace("-", ""), name=name, dex_number=1, base_species_id=name.lower(), forme=None,
                       types=types, base_stats=stats, abilities=abilities, weightkg=weight, gender=None, required_item=None, battle_only=None, is_mega=is_mega, is_legal=True)


KINGAMBIT = species("kingambit", "Kingambit", ("Dark", "Steel"), {"hp": 100, "atk": 135, "def": 120, "spa": 60, "spd": 85, "spe": 50}, ("Defiant", "Supreme Overlord", "Pressure"), 120)
MEGA_X = species("charizard-mega-x", "Charizard-Mega-X", ("Fire", "Dragon"), {"hp": 78, "atk": 130, "def": 111, "spa": 130, "spd": 85, "spe": 100}, ("Tough Claws",), 110.5, is_mega=True)
INCINEROAR = species("incineroar", "Incineroar", ("Fire", "Dark"), {"hp": 95, "atk": 115, "def": 90, "spa": 80, "spd": 90, "spe": 60}, ("Blaze", "Intimidate"), 83)

MOVES = {
    "kowtowcleave": MoveInfo("kowtowcleave", "Kowtow Cleave", "dark", "physical", 85, 100, 10, 0, "normal", "", True, MoveMechanics(contact=True, slicing=True)),
    "flareblitz": MoveInfo("flareblitz", "Flare Blitz", "fire", "physical", 120, 100, 15, 0, "normal", "", True, MoveMechanics(contact=True, recoil=(33, 100), secondaries=True)),
    "protect": MoveInfo("protect", "Protect", "normal", "status", None, None, 10, 4, "self", "", True),
    "earthquake": MoveInfo("earthquake", "Earthquake", "ground", "physical", 100, 100, 10, 0, "allAdjacent", "", True),
}


class FakeCatalogs:
    def __init__(self):
        self.species = {s.canonical_id: s for s in (KINGAMBIT, MEGA_X, INCINEROAR)}
        self.items = {"life-orb": SimpleNamespace(display_name="Life Orb", canonical_id="life-orb")}

    def species_for(self, canonical_id):
        return self.species.get(canonical_id)

    def move_by_name(self, name):
        return MOVES.get((name or "").lower().replace(" ", "").replace("-", ""))

    def item_for(self, reference):
        if not reference:
            return None
        return self.items.get(reference) or next((i for i in self.items.values() if i.display_name.lower() == reference.lower()), None)


def slot(species_id, *, form_id="base", is_mega=False, item=None, ability=None, points=None, nature=None, moves=(), display="Kingambit"):
    stats = PokemonStats(hp=100, attack=135, defense=120, sp_atk=60, sp_def=85, speed=50)
    entry = SimpleNamespace(pokemon=SimpleNamespace(canonical_id=species_id, display_name=display, abilities=[SimpleNamespace(name="defiant")]))
    member = SimpleNamespace(selected_form=form_id, item=item, ability=ability, points=points or {}, nature=nature, moveset=[SimpleNamespace(name=m) for m in moves])
    form = SimpleNamespace(form_id=form_id, label="Mega Charizard X" if is_mega else display, types=("dark", "steel"), stats=stats, is_mega=is_mega)
    return SimpleNamespace(entry=entry, member=member, form=form, item=SimpleNamespace(display_name=item) if item else None)


class TestBuilders(unittest.TestCase):
    def setUp(self):
        self.catalogs = FakeCatalogs()

    def test_calc_stat_table_accepts_both_key_styles(self):
        self.assertEqual(calc_stat_table({"attack": 32, "spe": 2, "hp": 0}), {"atk": 32, "spe": 2})
        self.assertEqual(calc_stat_table(None), {})

    def test_build_from_slot_carries_the_set(self):
        s = slot("kingambit", item="Life Orb", ability="supreme-overlord", points={"attack": 32, "speed": 32, "hp": 2}, nature="Adamant", moves=("Kowtow Cleave", "Protect"))
        built = build_from_slot(s, self.catalogs)
        self.assertEqual(built.pokemon.name, "Kingambit")
        self.assertEqual((built.pokemon.ability, built.pokemon.item, built.pokemon.nature), ("Supreme Overlord", "Life Orb", "Adamant"))
        self.assertEqual(built.pokemon.points, {"atk": 32, "spe": 32, "hp": 2})
        self.assertEqual(built.pokemon.raw_stats()["atk"], 205)
        self.assertEqual(built.moves, ("Kowtow Cleave", "Protect"))
        self.assertEqual(built.assumptions, ())

    def test_build_from_slot_defaults_and_mega_form(self):
        built = build_from_slot(slot("kingambit"), self.catalogs)
        self.assertEqual(built.pokemon.ability, "Defiant", "the species' first ability, and it is reported")
        self.assertIn("no ability set: Defiant", built.assumptions)
        self.assertIn("no stat points set", built.assumptions)
        self.assertIn("no nature set: neutral", built.assumptions)
        mega = build_from_slot(slot("charizard", form_id="charizard-mega-x", is_mega=True, display="Charizard"), self.catalogs)
        self.assertEqual((mega.pokemon.name, mega.pokemon.weightkg), ("Charizard-Mega-X", 110.5))
        unknown = build_from_slot(slot("garchomp", display="Garchomp"), self.catalogs)
        self.assertEqual(unknown.pokemon.name, "Garchomp")
        self.assertEqual(unknown.pokemon.weightkg, 0.0)
        self.assertTrue(any("weight unknown" in a for a in unknown.assumptions))
        self.assertIsNone(build_from_slot(SimpleNamespace(entry=None, member=None, form=None), self.catalogs))

    def test_build_from_roster_member(self):
        row = SimpleNamespace(canonical_id="incineroar", species_name="Incineroar")
        parsed = SimpleNamespace(ability_name="Intimidate", item_name="Life Orb", points={"hp": 32, "attack": 32, "defense": 2}, nature="Adamant", moves=("Flare Blitz", "Protect"))
        built = build_from_roster_member(row, parsed, self.catalogs)
        self.assertEqual((built.pokemon.ability, built.pokemon.item, built.pokemon.points), ("Intimidate", "Life Orb", {"hp": 32, "atk": 32, "def": 2}))
        self.assertEqual(built.moves, ("Flare Blitz", "Protect"))
        bare = build_from_roster_member(row, None, self.catalogs)
        self.assertEqual(bare.pokemon.abilities[0], "Blaze")
        self.assertEqual(len(bare.assumptions), 4)
        self.assertIsNone(build_from_roster_member(SimpleNamespace(canonical_id="mew", species_name="Mew"), None, self.catalogs))

    def test_moves_and_matchup(self):
        self.assertIsNone(build_calc_move("Nope", self.catalogs))
        move = build_calc_move("Flare Blitz", self.catalogs)
        self.assertEqual((move.bp, move.type, move.recoil), (120, "Fire", (33, 100)))
        a = build_from_slot(slot("kingambit", points={"attack": 32}, nature="Adamant", moves=("Kowtow Cleave", "Protect", "Earthquake")), self.catalogs)
        d = build_from_roster_member(SimpleNamespace(canonical_id="incineroar", species_name="Incineroar"), None, self.catalogs)
        results = matchup(a, a.moves, d, default_field(), self.catalogs)
        self.assertEqual([r.move_name for r in results], ["Kowtow Cleave", "Earthquake"], "status moves skipped")
        self.assertGreater(results[0].result.range()[0], 0)
        self.assertLess(results[1].result.range()[1], results[1].result.range()[1] / 0.75 + 1, "doubles spread")
        both = slot_vs_slot(slot("kingambit", moves=("Kowtow Cleave",)), slot("kingambit", moves=("Flare Blitz",)), default_field(False), self.catalogs)
        self.assertEqual(([r.move_name for r in both[0]], [r.move_name for r in both[1]]), (["Kowtow Cleave"], ["Flare Blitz"]))
        self.assertEqual(pokemon_from_species(KINGAMBIT, status="frozen").status, "", "unknown status codes are dropped")


if __name__ == "__main__":
    unittest.main()
