"""Unit tests for Limitless, Victory Road, and VRPaste HTTP providers."""

import unittest
from unittest.mock import MagicMock, patch


def _json_response(payload, status_code: int = 200) -> MagicMock:
    """Builds a stub `requests.Response` returning *payload* from `.json()`."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _html_response(html: str, status_code: int = 200) -> MagicMock:
    """Builds a stub `requests.Response` carrying raw HTML bytes."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = html.encode("utf-8")
    resp.raise_for_status.return_value = None
    return resp

from pokemon_champions_planning_tool.infrastructure.providers import (
    LimitlessProvider,
    VictoryRoadProvider,
    VRPasteProvider,
)
from pokemon_champions_planning_tool.infrastructure.providers.victory_road_provider import (
    DIVISION_MASTERS,
    DIVISION_OTHER,
)


class TestTournamentProviders(unittest.TestCase):

    def test_limitless_provider_fetch_tournaments(self):
        """Test LimitlessProvider parses tournament list correctly."""
        mock_payload = [
            {
                "id": "12345",
                "name": "Limitless Cup #1",
                "date": "2026-08-01T12:00:00Z",
                "format": "M-A",
                "players": 128,
                "organizer": "Limitless",
            }
        ]

        def _mock_get(url, params=None, headers=None, timeout=None):
            page = (params or {}).get("page")
            return _json_response(mock_payload if page == 1 else [])

        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".limitless_provider.requests.get",
            side_effect=_mock_get,
        ):
            provider = LimitlessProvider()
            tournaments = provider.fetch_champions_tournaments(max_age_days=365)

            self.assertEqual(len(tournaments), 1)
            self.assertEqual(tournaments[0].id, "12345")
            self.assertEqual(tournaments[0].name, "Limitless Cup #1")
            self.assertEqual(tournaments[0].format_code, "M-A")
            self.assertEqual(tournaments[0].player_count, 128)


    def test_limitless_provider_fetch_standings(self):
        """Test LimitlessProvider parses player standings and decklists (real API shape)."""
        # Real API: decklist is a flat list, field is 'attacks' (not 'moves'),
        # player name is 'name' field, handle is 'player' field.
        mock_payload = [
            {
                "name": "Alex",
                "player": "alex_player",
                "placing": 1,
                "record": {"wins": 7, "losses": 0, "ties": 0},
                "decklist": [
                    {
                        "id": "charizard",
                        "name": "Charizard",
                        "item": "Charizardite Y",
                        "ability": "Drought",
                        "nature": "Timid",
                        "attacks": ["Heat Wave", "Solar Beam", "Protect", "Overheat"],
                    }
                ],
            }
        ]

        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".limitless_provider.requests.get",
            return_value=_json_response(mock_payload),
        ):
            provider = LimitlessProvider()
            standings = provider.fetch_standings("12345")

            self.assertEqual(len(standings), 1)
            self.assertEqual(standings[0].player_handle, "Alex")
            self.assertEqual(standings[0].placement, 1)
            self.assertEqual(len(standings[0].members), 1)
            self.assertEqual(standings[0].members[0].display_name, "Charizard")
            self.assertEqual(standings[0].members[0].item, "Charizardite Y")
            self.assertEqual(standings[0].members[0].moves, ("Heat Wave", "Solar Beam", "Protect", "Overheat"))

    def test_vrpaste_provider_fetch_by_id(self):
        """Test VRPasteProvider parses paste JSON response."""
        mock_payload = {
            "title": "NAIC 2026 Winner",
            "format": "Regulation M-A",
            "teams": [
                {
                    "species": "Urshifu-Rapid-Strike",
                    "name": "Urshifu-Rapid-Strike",
                    "item": "Choice Scarf",
                    "ability": "Unseen Fist",
                    "nature": "Jolly",
                    "moves": ["Surging Strikes", "Close Combat", "Aqua Jet", "U-turn"],
                }
            ],
        }

        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".vrpaste_provider.requests.get",
            return_value=_json_response(mock_payload),
        ):
            provider = VRPasteProvider()
            result = provider.fetch_by_id("abc12345")

            self.assertEqual(result.paste_id, "abc12345")
            self.assertEqual(result.title, "NAIC 2026 Winner")
            self.assertEqual(len(result.members), 1)
            self.assertEqual(result.members[0].species, "Urshifu-Rapid-Strike")

    def test_victory_road_provider_fetch_event(self):
        """Test VictoryRoadProvider HTML parsing for official event standings."""
        mock_html = """
        <html>
            <body>
                <table>
                    <tr>
                        <td>1</td>
                        <td>8-1</td>
                        <td>Senior</td>
                        <td>Marco Silva ( Marco VGC )</td>
                        <td><a href="https://pokepast.es/a1b2c3d4">Pokepast Link</a></td>
                    </tr>
                </table>
            </body>
        </html>
        """

        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".victory_road_provider.requests.get",
            return_value=_html_response(mock_html),
        ):
            provider = VictoryRoadProvider()
            event_meta = {
                "slug": "2026-laic",
                "name": "2026 Latin America International Championships",
                "format": "Regulation M-A",
                "game": "Pokémon Champions",
            }
            res = provider.fetch_event(event_meta)

            self.assertIsNotNone(res)
            self.assertEqual(res.slug, "2026-laic")
            self.assertEqual(len(res.standings), 1)
            self.assertEqual(res.standings[0].player_name, "Marco VGC")
            self.assertEqual(res.standings[0].placement, 1)
            self.assertEqual(res.standings[0].paste_id, "a1b2c3d4")


if __name__ == "__main__":
    unittest.main()


def _standings_row(placement: int, player: str, paste_id: str) -> str:
    return (
        f"<tr><td>{placement}</td><td>9-2</td><td>{player} ( {player}VGC )</td>"
        f'<td><a href="https://pokepast.es/{paste_id}">paste</a></td></tr>'
    )


class TestVictoryRoadDivisions(unittest.TestCase):
    """Premier event pages publish Masters, Seniors and Juniors on one page, each
    with placements restarting at 1. Only Masters may reach the meta statistics."""

    # Masters table, then the Seniors & Juniors section, mirroring victoryroad.pro.
    MULTI_DIVISION_HTML = f"""
    <html><body>
      <h2><div class="title">Teams and results - Masters</div></h2>
      <h3>Masters Top 2</h3>
      <table>{_standings_row(1, "Paul", "aaaa1111")}{_standings_row(2, "Zach", "aaaa2222")}</table>
      <h2><div class="title">Teams and results - Seniors &amp; Juniors</div></h2>
      <h3>Seniors Top 1</h3>
      <table>{_standings_row(1, "Sena", "bbbb1111")}</table>
      <h3>Juniors Top 1</h3>
      <table>{_standings_row(1, "Juno", "cccc1111")}</table>
    </body></html>
    """

    # A community event with a single division and no division heading at all.
    SINGLE_DIVISION_HTML = f"""
    <html><body>
      <h2>Standings</h2>
      <table>{_standings_row(1, "Ana", "dddd1111")}{_standings_row(2, "Beto", "dddd2222")}</table>
    </body></html>
    """

    EVENT_META = {
        "slug": "2026-euic",
        "name": "2026 Europe International Championships",
        "format": "Regulation M-A",
        "game": "Pokémon Champions",
    }

    def _fetch(self, html: str, **kwargs):
        with patch(
            "pokemon_champions_planning_tool.infrastructure.providers"
            ".victory_road_provider.requests.get",
            return_value=_html_response(html),
        ):
            return VictoryRoadProvider().fetch_event(self.EVENT_META, **kwargs)

    def test_parser_labels_each_division(self):
        """Every paste link takes the division of its nearest preceding heading."""
        standings = VictoryRoadProvider()._parse_standings_from_html(self.MULTI_DIVISION_HTML)
        by_id = {s.paste_id: s.division for s in standings}
        self.assertEqual(by_id["aaaa1111"], DIVISION_MASTERS)
        self.assertEqual(by_id["aaaa2222"], DIVISION_MASTERS)
        self.assertEqual(by_id["bbbb1111"], DIVISION_OTHER)
        self.assertEqual(by_id["cccc1111"], DIVISION_OTHER)

    def test_masters_only_drops_seniors_and_juniors(self):
        """The default fetch keeps a single team per placement."""
        res = self._fetch(self.MULTI_DIVISION_HTML)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.standings), 2)
        self.assertEqual({s.division for s in res.standings}, {DIVISION_MASTERS})
        placements = [s.placement for s in res.standings]
        self.assertEqual(sorted(placements), [1, 2])
        self.assertEqual(len(placements), len(set(placements)), "no duplicate placements")
        self.assertEqual(res.standings[0].player_name, "PaulVGC")

    def test_opting_out_keeps_every_division(self):
        """masters_only=False preserves the raw page contents."""
        res = self._fetch(self.MULTI_DIVISION_HTML, masters_only=False)
        self.assertEqual(len(res.standings), 4)
        self.assertEqual(
            sum(1 for s in res.standings if s.placement == 1),
            3,
            "un-filtered pages really do carry three 1st places",
        )

    def test_page_without_division_headings_is_kept_whole(self):
        """A single-division event has no division heading; nothing may be dropped."""
        res = self._fetch(self.SINGLE_DIVISION_HTML)
        self.assertIsNotNone(res, "single-division events must not be filtered away")
        self.assertEqual(len(res.standings), 2)
        self.assertEqual({s.division for s in res.standings}, {DIVISION_MASTERS})

    def test_combined_heading_is_treated_as_non_masters(self):
        """A heading naming both Seniors and Juniors must not be read as Masters."""
        html = f"""<html><body>
          <h3>Seniors &amp; Juniors Top 1</h3>
          <table>{_standings_row(1, "Sena", "bbbb1111")}</table>
        </body></html>"""
        self.assertIsNone(self._fetch(html), "nothing Masters-eligible remains")
