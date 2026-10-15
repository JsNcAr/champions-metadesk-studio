"""The daily update check: version order, the GitHub request, the once-a-day gate, and the
notice in Settings and at startup."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests
from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool import __version__
from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401 - registers the tables for create_all
from pokemon_champions_planning_tool.config import USER_AGENT
from pokemon_champions_planning_tool.services import update_check
from pokemon_champions_planning_tool.services.update_check import Release, is_newer, parse_version


def _response(status=200, payload=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = payload if payload is not None else {}
    return resp


LATEST = {"tag_name": "v9.9.9", "html_url": "https://github.com/JsNcAr/champions-metadesk-studio/releases/tag/v9.9.9",
          "published_at": "2026-10-20T10:00:00Z"}


class TestVersions(unittest.TestCase):
    def test_order(self):
        self.assertTrue(is_newer("0.8.0", "0.7.0"))
        self.assertTrue(is_newer("v0.10.0", "0.9.0"), "numbers, not text")
        self.assertTrue(is_newer("0.8.0", "0.8.0-rc.1"), "the release is newer than its candidate")
        self.assertTrue(is_newer("0.8.0-rc.2", "0.8.0-rc.1"))
        self.assertFalse(is_newer("0.7.0", "0.7.0"))
        self.assertFalse(is_newer("0.6.9", "0.7.0"))

    def test_an_unreadable_tag_is_never_newer(self):
        self.assertIsNone(parse_version("latest"))
        self.assertFalse(is_newer("latest", "0.7.0"))
        self.assertFalse(is_newer("1.0.0", "dev"))


class TestFetchLatest(unittest.TestCase):
    def test_reads_the_release_and_sends_the_app_user_agent(self):
        with patch.object(update_check.requests, "get", return_value=_response(200, LATEST)) as get:
            release = update_check.fetch_latest()
        self.assertEqual(release, Release("v9.9.9", "9.9.9", LATEST["html_url"], LATEST["published_at"]))
        headers = get.call_args.kwargs["headers"]
        self.assertEqual(headers["User-Agent"], USER_AGENT)
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(get.call_args.args[0], update_check.RELEASES_API)

    def test_no_answer_is_none_and_a_warning(self):
        for label, kwargs in (("404", {"return_value": _response(404)}),
                              ("offline", {"side_effect": requests.ConnectionError("offline")}),
                              ("odd body", {"return_value": _response(200, {"name": "no tag"})})):
            with self.subTest(label), patch.object(update_check.requests, "get", **kwargs), \
                    self.assertLogs("pokemon_champions_planning_tool.services.update_check", "WARNING"):
                self.assertIsNone(update_check.fetch_latest())


class TestCheckForUpdate(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_asks_once_a_day_unless_forced_and_remembers_the_answer(self):
        with patch.object(update_check.requests, "get", return_value=_response(200, LATEST)) as get:
            first = update_check.check_for_update(self.session)
            again = update_check.check_for_update(self.session)
            forced = update_check.check_for_update(self.session, force=True)
        self.assertEqual(first.version, "9.9.9")
        self.assertIsNone(again, "not asked again the same day")
        self.assertEqual(forced.version, "9.9.9")
        self.assertEqual(get.call_count, 2)
        self.assertEqual(update_check.stored_latest(self.session).tag, "v9.9.9")
        self.assertTrue(update_check.last_checked(self.session))

    def test_an_older_or_equal_release_is_not_offered_but_is_remembered(self):
        with patch.object(update_check.requests, "get", return_value=_response(200, {**LATEST, "tag_name": f"v{__version__}"})):
            self.assertIsNone(update_check.check_for_update(self.session))
        self.assertEqual(update_check.stored_latest(self.session).version, __version__)

    def test_one_notification_per_version(self):
        release = Release("v9.9.9", "9.9.9", "https://example.org")
        self.assertTrue(update_check.claim_notification(self.session, release))
        self.assertFalse(update_check.claim_notification(self.session, release))
        self.assertTrue(update_check.claim_notification(self.session, Release("v9.9.10", "9.9.10", "https://example.org")))


class TestUpdateUi(unittest.TestCase):
    def setUp(self):
        from _ui_stubs import StubPage
        from pokemon_champions_planning_tool.ui.context import AppContext

        self.page = StubPage()
        self.ctx = AppContext(self.page)

    def test_the_about_row_shows_a_newer_version_and_the_switch_saves(self):
        from pokemon_champions_planning_tool.ui.views.settings.update_row import UpdateRow

        store = MagicMock()
        store.update_status.return_value = (Release("v9.9.9", "9.9.9", "https://example.org"), "2026-10-15T10:00:00+00:00")
        row = UpdateRow(self.ctx, store)
        row.refresh()
        self.assertIn("9.9.9 is available", row._line.value)
        self.assertTrue(row._download.visible)
        store.update_status.return_value = (Release(f"v{__version__}", __version__, "https://example.org"), "2026-10-15T10:00:00+00:00")
        row.refresh()
        self.assertIn("up to date", row._line.value)
        self.assertFalse(row._download.visible)
        row._daily.value = False
        row._daily.on_change(MagicMock(control=row._daily))
        self.assertIs(self.ctx.prefs.get(update_check.PREF_ENABLED), False)

    def test_startup_check_toasts_once_and_respects_the_switch(self):
        import flet as ft

        from pokemon_champions_planning_tool.ui import app

        release = Release("v9.9.9", "9.9.9", "https://example.org")
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        with patch.object(app, "UPDATE_CHECK_DELAY_S", 0), patch.object(app, "get_session", return_value=session), \
                patch.object(update_check, "check_for_update", return_value=release), \
                patch.object(update_check, "claim_notification", side_effect=[True, False]):
            app._start_update_check(self.ctx)
            app._start_update_check(self.ctx)
        toasts = [d for d in self.page.dialogs if isinstance(d, ft.SnackBar)]
        self.assertEqual(len(toasts), 1, "one toast per version")

        self.ctx.prefs.set(update_check.PREF_ENABLED, False)
        with patch.object(update_check, "check_for_update") as check:
            app._start_update_check(self.ctx)
        check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
