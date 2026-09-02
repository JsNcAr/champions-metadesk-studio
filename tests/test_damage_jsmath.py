"""JavaScript-faithful rounding and overflow helpers used by the damage engine."""

import unittest

from pokemon_champions_planning_tool.domain.damage.jsmath import chain_mods, js_round, js_shr12, of16, of32, poke_round


class TestJsMath(unittest.TestCase):
    def test_poke_round_rounds_half_down(self):
        self.assertEqual(poke_round(2.5), 2)
        self.assertEqual(poke_round(2.50001), 3)
        self.assertEqual(poke_round(2.49), 2)
        self.assertEqual(poke_round(7.0), 7)

    def test_js_round_rounds_half_up(self):
        self.assertEqual(js_round(2.5), 3)
        self.assertEqual(js_round(3.5), 4, "not banker's rounding")
        self.assertEqual(js_round(-1.5), -1)
        self.assertEqual(js_round(2.4), 2)

    def test_overflow(self):
        self.assertEqual(of16(65535), 65535)
        self.assertEqual(of16(65536), 0)
        self.assertEqual(of16(70000), 4464)
        self.assertEqual(of32(4294967295), 4294967295)
        self.assertEqual(of32(4294967296 + 5), 5)

    def test_shr12_wraps_like_int32(self):
        self.assertEqual(js_shr12(4096 * 6144 + 2048), 6144)
        self.assertEqual(js_shr12(2**31), -524288, "bit 31 is the sign in JS")
        self.assertEqual(js_shr12(-4096), -1)

    def test_chain_mods_bounds_and_skip(self):
        self.assertEqual(chain_mods([], 41, 131072), 4096)
        self.assertEqual(chain_mods([4096, 4096], 41, 131072), 4096)
        self.assertEqual(chain_mods([6144], 41, 131072), 6144)
        self.assertEqual(chain_mods([6144, 6144], 41, 131072), 9216)
        self.assertEqual(chain_mods([5324, 4915], 41, 131072), 6389, "Life Orb then Expert Belt, rounded at each step")
        self.assertEqual(chain_mods([8192] * 6, 41, 131072), 131072)
        self.assertEqual(chain_mods([2048] * 8, 41, 131072), 41)


if __name__ == "__main__":
    unittest.main()
