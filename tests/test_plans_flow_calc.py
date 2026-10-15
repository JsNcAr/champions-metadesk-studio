"""Battle-flow damage: a single-target hit with its KO chance, a spread move on two foes
(×0.75) or one, the Mega form only from the turn it Mega Evolves, and the cache."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_plans_grid import gambit, roar  # noqa: E402
from test_ui_calc import CHARIZARD, INCINEROAR, ITEMS, KINGAMBIT, MEGA_Y, MOVES  # noqa: E402

from pokemon_champions_planning_tool.ui.catalogs import Catalogs  # noqa: E402
from pokemon_champions_planning_tool.ui.views.calc.state import PokemonState, RivalMember  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans import flow_calc  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.flow import Action, OppRef, Scenario, Turn  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.flow_calc import action_hits, can_mega, form_for, hit_text  # noqa: E402
from pokemon_champions_planning_tool.ui.views.plans.model import MemberRef, Plan  # noqa: E402

ZARD_REF, GAMBIT_REF = MemberRef("c", "charizard"), MemberRef("k", "kingambit")
PLAN = Plan(plan_id="p", team_id="t", name="x", lead=(ZARD_REF, GAMBIT_REF),
            opponent=(RivalMember(gambit()), RivalMember(roar())))


def zard_slot():
    return PokemonState(species="charizard", nature="modest", points={"special_attack": 32, "speed": 32}, ability="Blaze",
                        item="Charizardite Y", moves=["Heat Wave", None, None, None])


def catalogs():
    return Catalogs(moves_by_id=MOVES, items_by_id=ITEMS,
                    species_by_canonical={s.canonical_id: s for s in (CHARIZARD, MEGA_Y, KINGAMBIT, INCINEROAR)})


def heat_wave(mega=False):
    return Action("move", "Heat Wave", "foes", mega=mega)


class TestForms(unittest.TestCase):
    def test_the_mega_form_only_once_it_has_mega_evolved(self):
        c = catalogs()
        self.assertTrue(can_mega(zard_slot(), c))
        self.assertFalse(can_mega(gambit(), c))
        self.assertEqual(form_for(zard_slot(), mega_now=False, catalogs=c).species, "charizard")
        mega = form_for(zard_slot(), mega_now=True, catalogs=c)
        self.assertEqual((mega.species, mega.ability), ("charizard-mega-y", "Drought"))
        saved_as_mega = replace(zard_slot(), species="charizard-mega-y", ability="Drought")
        self.assertEqual(form_for(saved_as_mega, mega_now=False, catalogs=c).species, "charizard", "base until it evolves")


class TestHits(unittest.TestCase):
    def setUp(self):
        self.c = catalogs()
        self.mine = {"c": zard_slot(), "k": gambit()}

    def sc(self, *turns, lead=(OppRef(0, "kingambit"), OppRef(1, "incineroar"))):
        return Scenario(scenario_id="s", plan_id="p", their_lead=lead, turns=tuple(turns))

    def test_a_single_target_hit_has_its_ko_chance(self):
        sc = self.sc(Turn((Action(), Action("move", "Kowtow Cleave", "foe", OppRef(1, "incineroar")))))
        hits = action_hits(PLAN, sc, self.mine, self.c)
        (hit,) = hits[(None, 0, 1)]
        self.assertEqual(hit.foe_index, 1)
        self.assertTrue(hit.result.ko_text)
        self.assertIn("Kowtow Cleave", hit.result.description)
        self.assertEqual(hit_text(hits[(None, 0, 1)], str), f"{hit.result.min_pct:g}–{hit.result.max_pct:g}% · {hit.result.ko_text}")

    def test_a_spread_move_hits_both_foes_at_three_quarters_or_one_in_full(self):
        both = action_hits(PLAN, self.sc(Turn((heat_wave(), Action()))), self.mine, self.c)[(None, 0, 0)]
        self.assertEqual([h.foe_index for h in both], [0, 1])
        self.assertEqual({h.result.targets for h in both}, {2})
        alone = action_hits(PLAN, self.sc(Turn((heat_wave(), Action()), their_field=(OppRef(0, "kingambit"),))), self.mine, self.c)[(None, 0, 0)]
        self.assertEqual([(h.foe_index, h.result.targets) for h in alone], [(0, 1)])
        self.assertGreater(alone[0].result.max_pct, both[0].result.max_pct, "no ×0.75 against a lone foe")
        self.assertIn(" / ", hit_text(both, lambda i: ["Kingambit", "Incineroar"][i]))

    def test_mega_evolving_changes_the_damage_from_that_turn(self):
        sc = self.sc(Turn((heat_wave(), Action())), Turn((heat_wave(mega=True), Action())), Turn((heat_wave(), Action())))
        hits = action_hits(PLAN, sc, self.mine, self.c)
        t1, t2, t3 = (hits[(None, i, 0)][0].result.max_pct for i in range(3))
        self.assertGreater(t2, t1, "Mega Charizard Y from T2")
        self.assertEqual(t2, t3, "and it stays Mega")

    def test_an_if_branch_attack_and_a_missing_member(self):
        sc = Scenario(scenario_id="s", their_lead=(OppRef(0, "kingambit"), OppRef(1, "incineroar")),
                      turns=(Turn(),), branches=())
        from pokemon_champions_planning_tool.ui.views.plans.flow import add_branch, set_action
        sc = add_branch(sc, 1, kind="other", text="they Protect")
        sc = set_action(sc, 0, 0, 0, heat_wave())
        self.assertIn((0, 0, 0), action_hits(PLAN, sc, self.mine, self.c))
        self.assertEqual(action_hits(PLAN, sc, {"k": gambit()}, self.c), {}, "a member gone from the team: no damage, no crash")

    def test_unchanged_attacks_come_from_the_cache(self):
        sc = self.sc(Turn((heat_wave(), Action("move", "Kowtow Cleave", "foe", OppRef(1, "incineroar")))))
        cache: dict = {}
        calls = []
        real = flow_calc._one

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)

        with patch.object(flow_calc, "_one", counting):
            action_hits(PLAN, sc, self.mine, self.c, cache=cache)
            first = len(calls)
            action_hits(PLAN, sc, self.mine, self.c, cache=cache)
        self.assertEqual(first, 3, "two Heat Wave targets and one Kowtow Cleave")
        self.assertEqual(len(calls), first)


if __name__ == "__main__":
    unittest.main()
