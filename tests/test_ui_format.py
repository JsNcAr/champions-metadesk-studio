"""Tests for UI formatting helpers: absolute_time, relative_time, thousands, plural."""

import unittest
from datetime import datetime, timedelta, timezone

from pokemon_champions_planning_tool.ui.format import (
    absolute_time,
    plural,
    relative_time,
    thousands,
)


class TestUiFormat(unittest.TestCase):
    def test_thousands(self):
        self.assertEqual(thousands(None), "—")
        self.assertEqual(thousands(0), "0")
        self.assertEqual(thousands(1000), "1,000")
        self.assertEqual(thousands(1234567), "1,234,567")

    def test_plural(self):
        self.assertEqual(plural(1, "team"), "1 team")
        self.assertEqual(plural(2, "team"), "2 teams")
        self.assertEqual(plural(0, "team"), "0 teams")
        self.assertEqual(plural(1, "entry", "entries"), "1 entry")
        self.assertEqual(plural(5, "entry", "entries"), "5 entries")

    def test_absolute_time_none(self):
        self.assertEqual(absolute_time(None), "never")

    def test_absolute_time_single_digit_day_no_leading_zero(self):
        dt = datetime(2026, 9, 5, 14, 30, tzinfo=timezone.utc)
        result = absolute_time(dt)
        local_day = str(dt.astimezone().day)
        self.assertTrue(result.startswith(f"{local_day} "))
        self.assertIn("Sep 2026", result)

    def test_absolute_time_double_digit_day(self):
        dt = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
        result = absolute_time(dt)
        local_day = str(dt.astimezone().day)
        self.assertTrue(result.startswith(f"{local_day} "))
        self.assertIn("Aug 2026", result)

    def test_relative_time_none(self):
        self.assertEqual(relative_time(None), "never")

    def test_relative_time_recent(self):
        now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(relative_time(now - timedelta(seconds=20), now=now), "just now")
        self.assertEqual(relative_time(now - timedelta(minutes=5), now=now), "5m ago")
        self.assertEqual(relative_time(now - timedelta(hours=3), now=now), "3h ago")
        self.assertEqual(relative_time(now - timedelta(days=2), now=now), "2d ago")

    def test_relative_time_older_than_week_formats_date_portably(self):
        now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
        past = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        result = relative_time(past, now=now)
        local_day = str(past.astimezone().day)
        self.assertEqual(result, f"{local_day} Sep 2026")

