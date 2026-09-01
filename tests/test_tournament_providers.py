"""Unit tests for Limitless, Victory Road, and VRPaste HTTP providers."""

import json
import unittest
from unittest.mock import MagicMock, patch

from pokemon_champions_planning_tool.infrastructure.providers import (
    LimitlessProvider,
    VictoryRoadProvider,
    VRPasteProvider,
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

        def _mock_urlopen(req, timeout=None):
            resp = MagicMock()
            if "page=1" in req.full_url:
                resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
            else:
                resp.read.return_value = json.dumps([]).encode("utf-8")
            return MagicMock(__enter__=MagicMock(return_value=resp))

        with patch("urllib.request.urlopen", side_effect=_mock_urlopen):
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

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_response

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

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_response

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

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_response = MagicMock()
            mock_response.read.return_value = mock_html.encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_response

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
