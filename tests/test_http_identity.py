"""Every HTTP request names the app, its version and its repository; none poses as a browser."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from pokemon_champions_planning_tool import __version__
from pokemon_champions_planning_tool.config import USER_AGENT

SRC = Path(__file__).resolve().parents[1] / "src" / "pokemon_champions_planning_tool"


def _sent_user_agents(call) -> list[str | None]:
    """Run ``call`` with requests.get/post recorded; the User-Agent of each request."""
    response = MagicMock(status_code=200, content=b"{}", text="{}", headers={}, url="https://pokepast.es/abc")
    response.json.return_value = {}
    with patch("requests.get", return_value=response) as get, patch("requests.post", return_value=response) as post:
        try:
            call()
        except Exception:  # noqa: BLE001 - only the request matters here, not what the caller makes of {}
            pass
    calls = get.call_args_list + post.call_args_list
    return [(c.kwargs.get("headers") or {}).get("User-Agent") for c in calls]


class TestUserAgent(unittest.TestCase):
    def test_it_names_the_app_its_version_and_repository(self):
        self.assertEqual(USER_AGENT, f"ChampionsMetaDeskStudio/{__version__} (+https://github.com/JsNcAr/champions-metadesk-studio)")

    def test_every_client_sends_it(self):
        from pokemon_champions_planning_tool.infrastructure import showdown
        from pokemon_champions_planning_tool.infrastructure import providers
        from pokemon_champions_planning_tool.infrastructure.pokeapi import pokeapi_retrieval
        from pokemon_champions_planning_tool.infrastructure.providers.limitless_provider import LimitlessProvider
        from pokemon_champions_planning_tool.infrastructure.providers.pokepast_provider import PokepastProvider
        from pokemon_champions_planning_tool.infrastructure.providers.showdown_moves_provider import ShowdownMovesProvider
        from pokemon_champions_planning_tool.infrastructure.providers.victory_road_provider import VictoryRoadProvider

        clients = {
            "Victory Road": lambda: VictoryRoadProvider()._fetch_html("https://victoryroad.pro/2026-season-calendar/"),
            "Limitless": lambda: LimitlessProvider()._get("/tournaments"),
            "Pokepast fetch": lambda: PokepastProvider().fetch_by_id("abc"),
            "Pokepast publish": lambda: PokepastProvider().publish(title="t", paste_text="Pikachu"),
            "Showdown moves": lambda: ShowdownMovesProvider()._get_text("https://play.pokemonshowdown.com/data/moves.json"),
            "Showdown items": showdown._fetch_base_items_ts,
            "PokéAPI": lambda: pokeapi_retrieval._get_json("https://pokeapi.co/api/v2/pokemon/pikachu"),
            "PokéAPI items": lambda: providers._fetch_pokeapi_item_detail("leftovers"),
        }
        for name, call in clients.items():
            with self.subTest(name):
                sent = _sent_user_agents(call)
                self.assertTrue(sent, f"{name} made no request")
                self.assertEqual(set(sent), {USER_AGENT})

    def test_no_source_file_poses_as_a_browser(self):
        offenders = [p.relative_to(SRC) for p in SRC.rglob("*.py") if "Mozilla/" in p.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
