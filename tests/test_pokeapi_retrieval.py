"""PokéAPI adapter: species whose default form lives under a suffixed slug."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

from pokemon_champions_planning_tool.infrastructure.pokeapi import pokeapi_retrieval as api


class _Response:
    def __init__(self, status: int, body: dict | None = None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(response=self)


_MALE = {
    "id": 902,
    "species": {"name": "basculegion"},
    "types": [{"type": {"name": "water"}}, {"type": {"name": "ghost"}}],
    "sprites": {"front_default": "https://x/902.png"},
    "stats": [
        {"stat": {"name": "hp"}, "base_stat": 120},
        {"stat": {"name": "attack"}, "base_stat": 112},
        {"stat": {"name": "defense"}, "base_stat": 65},
        {"stat": {"name": "special-attack"}, "base_stat": 80},
        {"stat": {"name": "special-defense"}, "base_stat": 75},
        {"stat": {"name": "speed"}, "base_stat": 78},
    ],
    "abilities": [{"ability": {"name": "swift-swim", "url": "u"}, "slot": 1, "is_hidden": False}],
}
_SPECIES = {
    "varieties": [
        {"is_default": True, "pokemon": {"name": "basculegion-male"}},
        {"is_default": False, "pokemon": {"name": "basculegion-female"}},
    ]
}


class DefaultVarietyFallbackTests(unittest.TestCase):
    def setUp(self):
        api.get_official_stats.cache_clear()
        self.calls: list[str] = []

    def _fake_get(self, routes):
        def _get(url, timeout=None):
            self.calls.append(url)
            for suffix, response in routes.items():
                if url.endswith(suffix):
                    return response
            return _Response(404)

        return _get

    def test_species_without_a_direct_entry_resolves_through_its_default_form(self):
        routes = {"/pokemon-species/basculegion": _Response(200, _SPECIES), "/pokemon/basculegion-male": _Response(200, _MALE)}
        with patch.object(api.requests, "get", self._fake_get(routes)):
            pokemon = api.get_official_stats("Basculegion")
        self.assertIsNotNone(pokemon)
        self.assertEqual(pokemon.canonical_id, "basculegion")  # the species slug, not the form's
        self.assertEqual(pokemon.display_name, "Basculegion")
        self.assertEqual(pokemon.species_name, "basculegion")
        self.assertEqual(pokemon.form_name, "Male")  # the default form is named, not hidden
        self.assertEqual(pokemon.qualified_name, "Basculegion (Male)")
        self.assertEqual(pokemon.types, ["water", "ghost"])
        self.assertEqual(pokemon.stats.hp, 120)
        self.assertEqual(pokemon.dex_number, 902)
        self.assertFalse(pokemon.is_stub)
        self.assertEqual([u.rsplit("/v2/", 1)[1] for u in self.calls], ["pokemon/basculegion", "pokemon-species/basculegion", "pokemon/basculegion-male"])

    def test_unknown_name_is_none_after_both_lookups(self):
        with patch.object(api.requests, "get", self._fake_get({})):
            self.assertIsNone(api.get_official_stats("Notamon"))
        self.assertEqual(len(self.calls), 2)

    def test_direct_hit_does_not_touch_the_species_endpoint(self):
        routes = {"/pokemon/kingambit": _Response(200, {**_MALE, "id": 983, "species": {"name": "kingambit"}})}
        with patch.object(api.requests, "get", self._fake_get(routes)):
            pokemon = api.get_official_stats("Kingambit")
        self.assertEqual(pokemon.canonical_id, "kingambit")
        self.assertEqual(len(self.calls), 1)

    def test_throttling_raises_unavailable_not_none(self):
        with patch.object(api.requests, "get", self._fake_get({"/pokemon/basculegion": _Response(503)})):
            with self.assertRaises(api.PokeApiUnavailable):
                api.get_official_stats("Basculegion")
        api.get_official_stats.cache_clear()
        routes = {"/pokemon-species/basculegion": _Response(403)}
        with patch.object(api.requests, "get", self._fake_get(routes)):
            with self.assertRaises(api.PokeApiUnavailable):
                api.get_official_stats("Basculegion")


if __name__ == "__main__":
    unittest.main()
