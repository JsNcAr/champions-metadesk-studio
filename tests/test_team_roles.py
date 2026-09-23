"""The team role checklist: who brings speed control, Fake Out, Intimidate and the rest."""

import unittest

from pokemon_champions_planning_tool.domain.moves import MoveInfo
from pokemon_champions_planning_tool.domain.team_roles import RoleMember, team_roles


def move(name, *, target="normal", priority=0, category="physical"):
    return MoveInfo(name.lower().replace(" ", ""), name, "normal", category, 80, 100, 10, priority, target, "", True)


TEAM = [
    RoleMember(1, "Incineroar", (move("Fake Out", priority=3), move("Flare Blitz"), move("Parting Shot", category="status"), move("Protect", category="status")), "Intimidate"),
    RoleMember(2, "Whimsicott", (move("Tailwind", category="status"), move("Moonblast", category="special"), "Encore"), "Prankster"),
    RoleMember(3, "Garchomp", (move("Earthquake", target="allAdjacent"), move("Protect", category="status")), "Rough Skin"),
    RoleMember(4, "Tyranitar", (move("Rock Slide", target="allAdjacentFoes"), move("Sucker Punch", priority=1)), "Sand Stream"),
]


class TestTeamRoles(unittest.TestCase):
    def roles(self, members=TEAM, **kw):
        return {c.key: c for c in team_roles(members, **kw)}

    def test_roles_and_who_provides_them(self):
        roles = self.roles()
        self.assertEqual(roles["speed_control"].providers, ("Whimsicott",))
        self.assertEqual(roles["fake_out"].providers, ("Incineroar",))
        self.assertEqual(roles["intimidate"].providers, ("Incineroar",))
        self.assertEqual(roles["weather"].providers, ("Tyranitar",))
        self.assertEqual(roles["spread"].providers, ("Garchomp", "Tyranitar"), "Earthquake and Rock Slide hit both foes")
        self.assertEqual(roles["priority"].providers, ("Tyranitar",), "Fake Out is its own role, not priority damage")
        self.assertEqual(roles["pivot"].providers, ("Incineroar",))
        self.assertEqual(roles["support"].providers, ("Whimsicott",), "a plain move name (Encore) counts too")
        self.assertEqual(roles["redirection"].status, "missing")
        self.assertIn("Follow Me", roles["redirection"].note)

    def test_protect_count_is_advice(self):
        protect = self.roles()["protect"]
        self.assertEqual(protect.status, "info", "2 of 4: doubles teams usually carry more")
        self.assertIn("2 of 4", protect.note)

    def test_singles_skips_doubles_only_roles(self):
        roles = self.roles(doubles=False)
        for key in ("fake_out", "redirection", "spread", "support"):
            self.assertNotIn(key, roles)
        self.assertEqual(roles["protect"].status, "ok")

    def test_an_empty_team(self):
        roles = self.roles([])
        self.assertNotIn("protect", roles)
        self.assertTrue(all(c.status == "missing" for c in roles.values()))


if __name__ == "__main__":
    unittest.main()
