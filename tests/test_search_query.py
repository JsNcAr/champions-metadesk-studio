import unittest

from pokemon_champions_planning_tool.domain.search import parse_search_query, remove_query_token


class TestSearchQueryParsing(unittest.TestCase):
    def test_empty_and_whitespace(self):
        self.assertEqual(parse_search_query("").includes, ())
        self.assertEqual(parse_search_query("").excludes, ())
        self.assertEqual(parse_search_query(None).includes, ())
        self.assertEqual(parse_search_query("   ").tokens, ())
        self.assertEqual(parse_search_query("- !").tokens, ())

    def test_single_inclusion(self):
        res = parse_search_query("pelipper")
        self.assertEqual(res.includes, ("pelipper",))
        self.assertEqual(res.excludes, ())
        self.assertEqual(len(res.tokens), 1)
        self.assertFalse(res.tokens[0].is_neg)
        self.assertEqual(res.tokens[0].value, "pelipper")

    def test_single_exclusion(self):
        res = parse_search_query("-incineroar")
        self.assertEqual(res.includes, ())
        self.assertEqual(res.excludes, ("incineroar",))
        self.assertEqual(len(res.tokens), 1)
        self.assertTrue(res.tokens[0].is_neg)
        self.assertEqual(res.tokens[0].value, "incineroar")

    def test_inclusion_and_exclusion(self):
        res = parse_search_query("pelipper -archaludon")
        self.assertEqual(res.includes, ("pelipper",))
        self.assertEqual(res.excludes, ("archaludon",))
        self.assertEqual(len(res.tokens), 2)

    def test_exclamation_mark_prefix(self):
        res = parse_search_query("dondozo !tatsugiri")
        self.assertEqual(res.includes, ("dondozo",))
        self.assertEqual(res.excludes, ("tatsugiri",))

    def test_without_and_not_prefix(self):
        res1 = parse_search_query("pelipper without:archaludon")
        self.assertEqual(res1.includes, ("pelipper",))
        self.assertEqual(res1.excludes, ("archaludon",))

        res2 = parse_search_query("dondozo not:tatsugiri")
        self.assertEqual(res2.includes, ("dondozo",))
        self.assertEqual(res2.excludes, ("tatsugiri",))

    def test_quoted_phrases(self):
        res = parse_search_query('"iron hands" -"flutter mane"')
        self.assertEqual(res.includes, ("iron hands",))
        self.assertEqual(res.excludes, ("flutter mane",))

        # Unclosed quote
        res_unclosed = parse_search_query('pelipper -"iron hands')
        self.assertEqual(res_unclosed.includes, ("pelipper",))
        self.assertEqual(res_unclosed.excludes, ("iron hands",))

    def test_hyphenated_species_names(self):
        # ho-oh without prefix is an inclusion
        res_pos = parse_search_query("ho-oh ting-lu")
        self.assertEqual(res_pos.includes, ("ho-oh", "ting-lu"))
        self.assertEqual(res_pos.excludes, ())

        # -ho-oh or -iron-hands is an exclusion
        res_neg = parse_search_query("chien-pao -iron-hands -ho-oh")
        self.assertEqual(res_neg.includes, ("chien-pao",))
        self.assertEqual(res_neg.excludes, ("iron-hands", "ho-oh"))

    def test_comma_delimiters(self):
        res = parse_search_query("dondozo, -tatsugiri, !incineroar")
        self.assertEqual(res.includes, ("dondozo",))
        self.assertEqual(res.excludes, ("tatsugiri", "incineroar"))

    def test_remove_query_token(self):
        q = "pelipper -archaludon -dondozo"
        self.assertEqual(remove_query_token(q, "-archaludon"), "pelipper -dondozo")
        self.assertEqual(remove_query_token(q, "archaludon"), "pelipper -dondozo")

        q2 = "pelipper -dondozo"
        self.assertEqual(remove_query_token(q2, "-dondozo"), "pelipper")

        q3 = "pelipper"
        self.assertEqual(remove_query_token(q3, "pelipper"), "")


if __name__ == "__main__":
    unittest.main()

