"""Formats and mechanics: the registry, a team's own format, and the controls it allows."""

import shutil
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sqlmodel import SQLModel, create_engine

from _ui_stubs import StubPage, check_layout, serialise
from test_ui_team_store import _TeamStoreCase
from test_ui_team_view import _TeamViewCase

from pokemon_champions_planning_tool.domain.formats import (
    BUILTIN_FORMATS,
    DEFAULT_FORMAT_ID,
    MECHANICS,
    Format,
    Mechanic,
    custom_copy,
    format_for_regulation,
)
from pokemon_champions_planning_tool.infrastructure.database import database
from pokemon_champions_planning_tool.services.item_effect_service import validate_item_assignment
from pokemon_champions_planning_tool.ui import events
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.formats import PREF_CUSTOM, FormatRegistry
from pokemon_champions_planning_tool.ui.preferences import Preferences
from pokemon_champions_planning_tool.ui.views.settings.format_panel import FormatDialog, FormatPanel
from pokemon_champions_planning_tool.ui.views.team import TeamStore
from pokemon_champions_planning_tool.ui.views.team.view import TeamView

CHAMPIONS = BUILTIN_FORMATS[0]


def with_tera(format_id="custom-tera", name="With Tera", **changes) -> Format:
    return replace(custom_copy(CHAMPIONS, format_id, name), mechanics=frozenset({Mechanic.MEGA, Mechanic.TERA}), **changes)


class TestFormatDomain(unittest.TestCase):
    def test_champions_has_mega_and_nothing_else(self):
        self.assertEqual(CHAMPIONS.format_id, DEFAULT_FORMAT_ID)
        self.assertTrue(CHAMPIONS.has(Mechanic.MEGA))
        self.assertFalse(any(CHAMPIONS.has(m) for m in (Mechanic.TERA, Mechanic.Z_MOVE, Mechanic.DYNAMAX)))
        self.assertEqual(CHAMPIONS.mechanics_label, "Mega")
        self.assertEqual(with_tera().mechanics_label, "Mega · Terastallization")
        self.assertEqual([m for m, info in MECHANICS.items() if info.implemented], [Mechanic.MEGA, Mechanic.TERA])

    def test_round_trip_and_regulations(self):
        fmt = with_tera(game_type="singles", item_clause=False)
        self.assertEqual(Format.from_dict(fmt.to_dict()), fmt)
        self.assertEqual(Format.from_dict({"format_id": "x", "mechanics": ["mega", "warp_drive"]}).mechanics, frozenset({Mechanic.MEGA}),
                         "an unknown mechanic from a newer version is dropped")
        self.assertEqual(format_for_regulation("Regulation M-B"), CHAMPIONS)
        self.assertIsNone(format_for_regulation("Regulation H"))


class TestFormatRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.prefs = Preferences(Path(self.dir) / "prefs.json")
        self.registry = FormatRegistry(self.prefs)
        self.events = []
        self.registry.subscribe(self.events.append)

    def test_defaults_customs_and_persistence(self):
        self.assertEqual(self.registry.default(), CHAMPIONS)
        tera = self.registry.save_custom(with_tera())
        self.registry.set_default(tera.format_id)
        again = FormatRegistry(Preferences(self.prefs.path))
        self.assertEqual(again.default(), tera, "saved in preferences.json")
        self.assertEqual(again.for_team(None), tera)
        self.assertEqual(again.for_team(CHAMPIONS.format_id), CHAMPIONS)
        self.assertEqual(again.for_team("custom-gone"), tera, "a deleted format falls back to the default")
        self.assertEqual(len(self.events), 2)

    def test_built_ins_are_read_only_and_deleting_resets_the_default(self):
        with self.assertRaises(ValueError):
            self.registry.save_custom(replace(CHAMPIONS, name="Mine"))
        tera = self.registry.save_custom(with_tera())
        self.registry.save_custom(replace(tera, name="Renamed"))
        self.assertEqual([f.name for f in self.registry.custom()], ["Renamed"], "saving again replaces it")
        self.registry.set_default(tera.format_id)
        self.registry.delete_custom(tera.format_id)
        self.assertEqual(self.registry.default(), CHAMPIONS)

    def test_a_malformed_custom_entry_is_skipped(self):
        self.prefs.set(PREF_CUSTOM, [{"name": "no id"}, with_tera().to_dict()])
        self.assertEqual([f.format_id for f in self.registry.custom()], ["custom-tera"])

    def test_the_context_relays_changes_on_the_bus(self):
        ctx = AppContext(StubPage())
        heard = []
        ctx.bus.on(events.FORMAT_CHANGED, heard.append)
        ctx.formats.save_custom(with_tera())
        self.assertEqual(heard, [None])
        ctx.prefs = Preferences()
        self.assertEqual(ctx.formats.custom(), [], "new preferences, new registry")


class TestMigration(unittest.TestCase):
    def test_teams_gain_a_format_column(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        path = Path(folder) / "old.db"
        from pokemon_champions_planning_tool.infrastructure.database import models  # noqa: F401

        engine = create_engine(f"sqlite:///{path}")
        SQLModel.metadata.create_all(engine)
        engine.dispose()
        conn = sqlite3.connect(path)
        conn.execute("ALTER TABLE teams DROP COLUMN format_id")
        conn.execute("PRAGMA user_version = 11")
        conn.commit()
        conn.close()
        database.reset_engines()
        self.addCleanup(database.reset_engines)
        database.initialize_database(str(path))
        conn = sqlite3.connect(path)
        self.assertIn("format_id", {row[1] for row in conn.execute("PRAGMA table_info(teams)")})
        conn.close()


class TestRulesFollowTheFormat(_TeamStoreCase):
    def setUp(self):
        super().setUp()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)
        self.store.assign(2, self.lucario)

    def _custom(self, **changes):
        fmt = self.store.formats.save_custom(replace(custom_copy(CHAMPIONS, "custom-x", "Custom"), **changes))
        self.store.set_format(fmt.format_id)
        return fmt

    def test_a_team_keeps_its_own_format(self):
        self.assertIsNone(self.store.active_team_format_id)
        self.assertEqual(self.store.active_format, CHAMPIONS)
        fmt = self._custom(mechanics=frozenset({Mechanic.MEGA, Mechanic.TERA}))
        self.assertEqual(self.store.active_format, fmt)
        self.store.load()
        self.assertEqual(self.store.active_team_format_id, "custom-x", "saved on the team")
        copy_id = self.store.duplicate_team("Sun copy")
        self.assertEqual(next(t.format_id for t in self.store.teams if t.team_id == copy_id), "custom-x", "a copy keeps the format")
        self.store.set_format(None)
        self.assertEqual(self.store.active_format, CHAMPIONS)

    def test_one_mega_per_team_follows_the_format(self):
        self.store.set_item(1, "charizardite-x")
        self.store.set_item(2, "lucarionite")
        self.assertIn("2 Mega Stones", [c.label for c in self.store.summary.checks])
        self.assertIn("Only one", self.store.slot(2).validation.warning)
        self._custom(one_mega_per_team=False)
        self.assertNotIn("2 Mega Stones", [c.label for c in self.store.summary.checks])
        self.assertIsNone(self.store.slot(2).validation.warning)

    def test_without_mega_a_stone_unlocks_nothing(self):
        self._custom(mechanics=frozenset())
        self.store.set_item(1, "charizardite-x")
        slot = self.store.slot(1)
        self.assertFalse(slot.form.is_mega, "no Mega Evolution: the form stays base")
        self.assertIn("not part of this team's format", slot.validation.warning)
        self.assertIn("1 Mega Stone", [c.label for c in self.store.summary.checks])

    def test_item_clause_can_be_switched_off(self):
        self.store.set_item(1, "choice-band")
        self.store.set_item(2, "choice-band")
        self.assertIn("Duplicate items", [c.label for c in self.store.summary.checks])
        self._custom(item_clause=False)
        labels = [c.label for c in self.store.summary.checks]
        self.assertNotIn("Duplicate items", labels)
        self.assertNotIn("Items unique", labels)

    def test_validation_without_a_format_keeps_the_champions_rules(self):
        stone = self.catalogs.item_for("lucarionite")
        other = self.catalogs.item_for("charizardite-x")
        self.assertIsNotNone(validate_item_assignment(stone, "lucario", [other]).warning)
        self.assertIsNone(validate_item_assignment(stone, "lucario", [other], one_mega_per_team=False).warning)


class TestTeamViewShowsOnlyTheFormatsMechanics(_TeamViewCase):
    def setUp(self):
        super().setUp()
        self.store = TeamStore(self.ctx.catalogs, self.db.session, formats=self.ctx.formats)
        self.view = TeamView(self.ctx, self.store)
        self.view.ensure_loaded()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)

    def test_tera_appears_only_in_a_format_with_it(self):
        card = self.view.cards[0]
        self.assertFalse(card._tera.visible, "Champions has no Terastallization")
        self.assertTrue(card._form.visible, "Charizard's Mega forms: Champions has Mega Evolution")
        self.assertIn("Mega", self.view._format_label.value)
        tera = self.ctx.formats.save_custom(with_tera())
        self.ctx.formats.set_default(tera.format_id)          # FORMAT_CHANGED re-checks the team
        self.assertTrue(self.view.cards[0]._tera.visible)
        self.view._set_format(CHAMPIONS.format_id)            # the team's own format wins over the default
        self.assertFalse(self.view.cards[0]._tera.visible)
        labels = [getattr(i.content, "value", "") for i in self.view._format_menu.items]
        self.assertTrue(any(label.startswith("Default format") for label in labels))
        self.assertTrue(any("With Tera" in label for label in labels))
        serialise(self.view)

    def test_no_mega_hides_the_form_switch_and_the_stones(self):
        from pokemon_champions_planning_tool.ui.views.team.dialogs.item_picker import ItemPickerDialog

        no_mega = self.ctx.formats.save_custom(replace(custom_copy(CHAMPIONS, "custom-plain", "Plain"), mechanics=frozenset()))
        self.view._set_format(no_mega.format_id)
        self.assertFalse(self.view.cards[0]._form.visible)
        self.view._open_item_picker(1)
        picker = self.page.dialogs[-1]
        self.assertIsInstance(picker, ItemPickerDialog)
        compatible, others, incompatible = picker._candidates()
        self.assertEqual((compatible, incompatible), ([], []), "no Mega Stones offered")
        self.assertTrue(others)


class TestSettingsFormats(unittest.TestCase):
    def setUp(self):
        self.page = StubPage()
        self.ctx = AppContext(self.page)
        self.panel = FormatPanel(registry=self.ctx.formats, on_edit=lambda f: None, on_delete=lambda f: None, on_default=self.ctx.formats.set_default)

    def test_panel_shows_the_default_and_its_mechanics(self):
        self.assertEqual(self.panel._default.value, CHAMPIONS.format_id)
        labels = [chip._label.value for chip in self.panel._chips.controls]
        self.assertEqual(labels, ["Mega Evolution", "Terastallization", "Z-Moves", "Dynamax"])
        self.assertIn("one Mega per team", self.panel._rules.value)
        check_layout(self.panel)
        serialise(self.panel)

    def test_dialog_creates_a_custom_format(self):
        saved = []
        dialog = FormatDialog(registry=self.ctx.formats, fmt=None, on_saved=saved.append, on_close=lambda: None)
        self.assertTrue(dialog._mechanics[Mechanic.Z_MOVE].disabled, "not supported yet")
        dialog._name.value = "Reg M + Tera"
        dialog._mechanics[Mechanic.TERA].value = True
        dialog._game_type.selected = ["singles"]
        check_layout(dialog)
        serialise(dialog)
        dialog.save()
        fmt = saved[0]
        self.assertEqual((fmt.name, fmt.game_type, fmt.mechanics), ("Reg M + Tera", "singles", frozenset({Mechanic.MEGA, Mechanic.TERA})))
        self.panel.render()
        self.assertEqual(len(self.panel._custom.controls), 1)
        again = FormatDialog(registry=self.ctx.formats, fmt=None, on_saved=saved.append, on_close=lambda: None)
        again._name.value = "reg m + tera"
        again.save()
        self.assertTrue(again._error.visible, "names are unique")
        self.assertEqual(len(saved), 1)


class TestCalcFollowsTheDefaultFormat(unittest.TestCase):
    def test_mega_switch_and_singles(self):
        from test_ui_calc import CHARIZARD, catalogs
        from pokemon_champions_planning_tool.ui.views.calc import CalcStore

        registry = FormatRegistry()
        cats = catalogs()
        cats.species_by_canonical["charizard"] = CHARIZARD
        store = CalcStore(cats, session_factory=None, formats=registry)
        store.load()
        store.load_species("left", "charizard")
        store.set_item("left", "Charizardite Y")
        self.assertEqual(store.state.left.species, "charizard-mega-y", "Champions: the stone Mega Evolves")
        plain = registry.save_custom(replace(custom_copy(BUILTIN_FORMATS[1], "custom-plain", "Plain singles"), mechanics=frozenset()))
        registry.set_default(plain.format_id)
        self.assertFalse(store.mega_enabled)
        store.load_species("left", "charizard")
        store.set_item("left", "Charizardite Y")
        self.assertEqual(store.state.left.species, "charizard", "no Mega Evolution: the stone is just an item")
        store.reset()
        self.assertEqual(store.state.field.game_type, "singles", "a reset starts in the format's game type")


if __name__ == "__main__":
    unittest.main()
