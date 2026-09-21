"""Move catalogue: Showdown parsing, species keys, sync, usage, legality, picker and view option."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from sqlmodel import Session, SQLModel, create_engine

from _ui_stubs import StubPage, serialise
from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.moves import move_key, resolve_learnset_key
from pokemon_champions_planning_tool.domain.pokemon_identity import base_canonical_id
from pokemon_champions_planning_tool.infrastructure.database.models import (
    MegaEvolutionRecord,
    TournamentRecord,
    TournamentTeamMemberRecord,
    TournamentTeamRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, MoveRepository, TournamentRepository
from pokemon_champions_planning_tool.infrastructure.providers.showdown_moves_provider import (
    MoveCatalogPayload,
    build_catalog,
    parse_learnsets_ts,
    parse_move_overrides_ts,
)
from pokemon_champions_planning_tool.services.move_catalog_service import load_move_catalog, move_catalog_is_stale, sync_move_catalog
from pokemon_champions_planning_tool.services.tournament_service import TournamentService
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.context import AppContext
from pokemon_champions_planning_tool.ui.views.team import TeamStore
from pokemon_champions_planning_tool.ui.views.team.dialogs.move_picker import MovePickerDialog
from pokemon_champions_planning_tool.ui.views.team.view import TeamView

LEARNSETS_TS = """export const Learnsets = {
\tcharizard: {
\t\tlearnset: {
\t\t\tairslash: ["9M"],
\t\t\tflareblitz: ["9M"],
\t\t\theatwave: ["9M"],
\t\t\tprotect: ["9M"],
\t\t},
\t},
\tbasculegion: {
\t\tlearnset: {
\t\t\taquajet: ["9M"],
\t\t\tlastrespects: ["9M"],
\t\t},
\t},
};
"""
MOVES_TS = """export const Moves = {
\tanchorshot: {
\t\tinherit: true,
\t\tbasePower: 90,
\t},
\tknockoff: {
\t\tisNonstandard: "Past",
\t\ttier: "Illegal",
\t},
\tcrushclaw: {
\t\tinherit: true,
\t\tflags: { contact: 1, protect: 1, mirror: 1, metronome: 1, slicing: 1 },
\t},
\tfreezedry: {
\t\tinherit: true,
\t\tsecondary: undefined, // no inherit
\t},
\tmakeitrain: {
\t\tinherit: true,
\t\taccuracy: 95,
\t\tself: {
\t\t\tboosts: {
\t\t\t\tspa: -2,
\t\t\t},
\t\t},
\t},
\tburnup: {
\t\tinherit: true,
\t\tisNonstandard: null,
\t},
};
"""
MOVES_JSON = {
    "airslash": {"name": "Air Slash", "type": "Flying", "category": "Special", "basePower": 75, "accuracy": 95, "pp": 15, "priority": 0, "target": "normal", "shortDesc": "30% flinch."},
    "flareblitz": {"name": "Flare Blitz", "type": "Fire", "category": "Physical", "basePower": 120, "accuracy": 100, "pp": 15, "priority": 0, "target": "normal"},
    "heatwave": {"name": "Heat Wave", "type": "Fire", "category": "Special", "basePower": 95, "accuracy": 90, "pp": 10, "priority": 0, "target": "allAdjacentFoes"},
    "protect": {"name": "Protect", "type": "Normal", "category": "Status", "basePower": 0, "accuracy": True, "pp": 10, "priority": 4, "target": "self"},
    "knockoff": {"name": "Knock Off", "type": "Dark", "category": "Physical", "basePower": 65, "accuracy": 100, "pp": 20, "priority": 0, "target": "normal"},
    "anchorshot": {"name": "Anchor Shot", "type": "Steel", "category": "Physical", "basePower": 80, "accuracy": 100, "pp": 20, "priority": 0, "target": "normal"},
    "aquajet": {"name": "Aqua Jet", "type": "Water", "category": "Physical", "basePower": 40, "accuracy": 100, "pp": 20, "priority": 1, "target": "normal"},
    "lastrespects": {"name": "Last Respects", "type": "Ghost", "category": "Physical", "basePower": 50, "accuracy": 100, "pp": 10, "priority": 0, "target": "normal"},
    "paleowave": {"name": "Paleo Wave", "type": "Rock", "category": "Special", "basePower": 85, "accuracy": 100, "pp": 15, "priority": 0, "target": "normal", "isNonstandard": "CAP"},
}
# Moves with damage-formula fields; only the parsing test uses them so the counts above stay small.
MECHANICS_JSON = {
    "crushclaw": {"name": "Crush Claw", "type": "Normal", "category": "Physical", "basePower": 75, "accuracy": 95, "pp": 10, "priority": 0, "target": "normal", "flags": {"contact": 1}, "secondary": {"chance": 50}},
    "freezedry": {"name": "Freeze-Dry", "type": "Ice", "category": "Special", "basePower": 70, "accuracy": 100, "pp": 20, "priority": 0, "target": "normal", "secondary": {"chance": 10}},
    "makeitrain": {"name": "Make It Rain", "type": "Steel", "category": "Special", "basePower": 120, "accuracy": 100, "pp": 5, "priority": 0, "target": "allAdjacentFoes", "self": {"boosts": {"spa": -1}}},
    "burnup": {"name": "Burn Up", "type": "Fire", "category": "Special", "basePower": 130, "accuracy": 100, "pp": 5, "priority": 0, "target": "normal", "isNonstandard": "Past"},
    "mindblown": {"name": "Mind Blown", "type": "Fire", "category": "Special", "basePower": 150, "accuracy": 100, "pp": 5, "priority": 0, "target": "allAdjacent", "isNonstandard": "Past", "mindBlownRecoil": True},
    "wildcharge": {"name": "Wild Charge", "type": "Electric", "category": "Physical", "basePower": 90, "accuracy": 100, "pp": 15, "priority": 0, "target": "normal", "flags": {"contact": 1}, "recoil": [1, 4]},
    "bonerush": {"name": "Bone Rush", "type": "Ground", "category": "Physical", "basePower": 25, "accuracy": 90, "pp": 10, "priority": 0, "target": "normal", "multihit": [2, 5]},
    "foulplay": {"name": "Foul Play", "type": "Dark", "category": "Physical", "basePower": 95, "accuracy": 100, "pp": 15, "priority": 0, "target": "normal", "flags": {"contact": 1}, "overrideOffensivePokemon": "target"},
    "highjumpkick": {"name": "High Jump Kick", "type": "Fighting", "category": "Physical", "basePower": 130, "accuracy": 90, "pp": 10, "priority": 0, "target": "normal", "flags": {"contact": 1}, "hasCrashDamage": True},
}


def _payload() -> MoveCatalogPayload:
    removed, overrides = parse_move_overrides_ts(MOVES_TS)
    return build_catalog(MOVES_JSON, parse_learnsets_ts(LEARNSETS_TS), removed, overrides)


class TestParsing(unittest.TestCase):
    def test_learnsets_overrides_and_catalog(self):
        learnsets = parse_learnsets_ts(LEARNSETS_TS)
        self.assertEqual(learnsets["charizard"], ("airslash", "flareblitz", "heatwave", "protect"))
        removed, overrides = parse_move_overrides_ts(MOVES_TS)
        self.assertEqual(removed, frozenset({"knockoff"}))
        self.assertEqual(overrides["anchorshot"], {"basePower": 90})
        self.assertEqual(overrides["crushclaw"], {"flags": {"contact": 1, "protect": 1, "mirror": 1, "metronome": 1, "slicing": 1}})
        self.assertEqual(overrides["freezedry"], {"secondaries": False})
        self.assertEqual(overrides["makeitrain"], {"accuracy": 95, "self_boosts": {"spa": -2}})
        self.assertEqual(overrides["burnup"], {"isNonstandard": None})
        payload = build_catalog({**MOVES_JSON, **MECHANICS_JSON}, parse_learnsets_ts(LEARNSETS_TS), removed, overrides)
        by_id = {m.move_id: m for m in payload.moves}
        self.assertNotIn("paleowave", by_id, "CAP moves dropped")
        self.assertEqual(by_id["anchorshot"].power, 90, "override applied")
        self.assertFalse(by_id["knockoff"].is_legal)
        self.assertFalse(by_id["mindblown"].is_legal, "Past in the base data and untouched by the mod")
        self.assertTrue(by_id["burnup"].is_legal, "restored by the mod")
        self.assertEqual(by_id["crushclaw"].mechanics, {"contact": True, "slicing": True, "secondaries": True})
        self.assertEqual(by_id["freezedry"].mechanics, {}, "the mod removed the secondary")
        self.assertEqual(by_id["makeitrain"].mechanics, {"self_boosts": [["spa", -2]]})
        self.assertEqual(by_id["wildcharge"].mechanics, {"contact": True, "recoil": [1, 4]})
        self.assertEqual(by_id["bonerush"].mechanics, {"multihit": [2, 5]})
        self.assertEqual(by_id["foulplay"].mechanics, {"contact": True, "override_offensive_pokemon": "target"})
        self.assertEqual(by_id["highjumpkick"].mechanics, {"contact": True, "has_crash_damage": True})
        self.assertEqual(by_id["mindblown"].mechanics, {"mind_blown_recoil": True})
        self.assertIsNone(by_id["protect"].accuracy, "accuracy true -> never misses -> None")
        self.assertEqual(by_id["protect"].priority, 4)

    def test_species_keys(self):
        keys = {"charizard", "basculegion", "urshifurapidstrike", "rotomwash"}
        self.assertEqual(base_canonical_id("charizard-mega-y"), "charizard")
        self.assertEqual(resolve_learnset_key("charizard-mega-x", keys), "charizard")
        self.assertEqual(resolve_learnset_key("basculegion-male", keys), "basculegion")
        self.assertEqual(resolve_learnset_key("urshifu-rapid-strike", keys), "urshifurapidstrike")
        self.assertEqual(resolve_learnset_key("Rotom-Wash", keys), "rotomwash")
        self.assertIsNone(resolve_learnset_key("floette-eternal", keys))
        self.assertEqual(move_key("Fake Out"), "fakeout")


class _Db:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'moves.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


def _mon(cid, name, types):
    return Pokemon(canonical_id=cid, display_name=name, species_name=cid, types=types, stats=PokemonStats(hp=78, attack=84, defense=78, sp_atk=109, sp_def=85, speed=100))


class TestSyncAndUsage(unittest.TestCase):
    def setUp(self):
        self.db = _Db()

    def tearDown(self):
        self.db.close()

    def test_sync_replaces_catalog_and_is_cached_until_stale(self):
        provider = MagicMock(); provider.fetch_move_catalog.return_value = _payload()
        with self.db.session() as s:
            self.assertTrue(move_catalog_is_stale(s))
            res = sync_move_catalog(s, provider=provider)
            self.assertEqual((res["status"], res["moves"], res["species"], res["learnsets"]), ("synced", 8, 2, 6))
            self.assertEqual(sync_move_catalog(s, provider=provider)["status"], "cached")
            self.assertEqual(provider.fetch_move_catalog.call_count, 1)
            moves, learnsets = load_move_catalog(s)
            self.assertEqual(learnsets["charizard"], frozenset({"airslash", "flareblitz", "heatwave", "protect"}))
            self.assertFalse(moves["knockoff"].is_legal)
            self.assertEqual(moves["anchorshot"].mechanics.to_json(), {}, "mechanics round-trip through the table")
            meta = MoveRepository(s).get_meta()
            meta.schema_version = 1
            s.add(meta); s.commit()
            self.assertTrue(move_catalog_is_stale(s), "an older stored shape forces a re-sync")
            self.assertEqual(sync_move_catalog(s, provider=provider)["status"], "synced")
            self.assertEqual(provider.fetch_move_catalog.call_count, 2)
            # a forced sync with a smaller payload leaves no stale pairs behind
            provider.fetch_move_catalog.return_value = build_catalog(MOVES_JSON, {"charizard": ("protect",)}, frozenset(), {})
            sync_move_catalog(s, force=True, provider=provider)
            self.assertEqual(MoveRepository(s).count_learnsets(), 1)

    def test_mechanics_round_trip_through_the_table(self):
        removed, overrides = parse_move_overrides_ts(MOVES_TS)
        provider = MagicMock()
        provider.fetch_move_catalog.return_value = build_catalog({**MOVES_JSON, **MECHANICS_JSON}, parse_learnsets_ts(LEARNSETS_TS), removed, overrides)
        with self.db.session() as s:
            sync_move_catalog(s, provider=provider)
            moves, _ = load_move_catalog(s)
            self.assertEqual(moves["makeitrain"].mechanics.drops_stats("Special"), 2)
            self.assertEqual(moves["bonerush"].mechanics.multihit, (2, 5))
            self.assertEqual(moves["wildcharge"].mechanics.recoil, (1, 4))
            self.assertTrue(moves["crushclaw"].mechanics.slicing)
            self.assertFalse(moves["freezedry"].mechanics.secondaries)

    def test_move_usage_counts_megas_with_the_base_species(self):
        with self.db.session() as s:
            s.add(TournamentRecord(tournament_id="t", name="T", format_regulation="Regulation M-B", game_platform="Pokémon Champions"))
            s.commit()
            for cid, moves in (("charizard", ["Heat Wave", "Protect", "Air Slash", "Flare Blitz"]), ("charizard-mega-y", ["Heat Wave", "Protect", "Solar Beam", "Overheat"]), ("garchomp", ["Earthquake", "Protect"])):
                team = TournamentTeamRecord(tournament_id="t", player_name=cid, placement=1, showdown_text="x")
                s.add(team); s.commit()
                s.add(TournamentTeamMemberRecord(tournament_team_id=team.tournament_team_id, slot_position=1, canonical_id=cid, species_name=cid, moves=moves))
            s.commit()
            counts = TournamentRepository(s).move_usage("charizard")
            self.assertEqual(counts[:2], [("Heat Wave", 2), ("Protect", 2)])
            usage = TournamentService(s).move_usage("charizard")
            self.assertAlmostEqual(usage["heatwave"], 1.0)
            self.assertAlmostEqual(usage["solarbeam"], 0.5)
            self.assertNotIn("earthquake", usage)


class TestLegalityInTeamBuilder(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        with self.db.session() as s:
            sync_move_catalog(s, provider=MagicMock(fetch_move_catalog=MagicMock(return_value=_payload())))
            self.charizard = BoxRepository(s).upsert_box_entry(BoxEntry(pokemon=_mon("charizard", "Charizard", ["fire", "flying"]))).box_entry_id
            s.add(MegaEvolutionRecord(canonical_id="charizard-mega-y", species_name="charizard", display_name="Mega Charizard Y", types=["fire", "flying"], hp=78, attack=104, defense=78, special_attack=159, special_defense=115, speed=100, sprite_url=None))
            s.commit()
        self.catalogs = Catalogs.load(self.db.session)
        self.store = TeamStore(self.catalogs, self.db.session)
        self.store.load()
        self.store.create_team("Sun")
        self.store.assign(1, self.charizard)

    def tearDown(self):
        self.db.close()

    def test_catalog_legality_and_mega_fallback(self):
        c = self.catalogs
        self.assertTrue(c.has_moves)
        self.assertEqual(c.learnset_key("charizard-mega-y"), "charizard")
        self.assertTrue(c.move_legality("charizard", "Heat Wave"))
        self.assertFalse(c.move_legality("charizard-mega-y", "Knock Off"), "removed from Champions")
        self.assertFalse(c.move_legality("charizard", "Aqua Jet"))
        self.assertIsNone(c.move_legality("rillaboom", "Grassy Glide"), "no learnset -> unknown")
        self.assertIsNone(c.move_legality("charizard", ""))

    def test_store_flags_illegal_moves_and_health_check(self):
        self.store.set_move(1, 0, "Heat Wave")
        self.store.set_move(1, 1, "Aqua Jet")
        slot = self.store.slot(1)
        self.assertEqual([(m.name, m.legal) for m in slot.moves if m], [("Heat Wave", True), ("Aqua Jet", False)])
        self.assertEqual(slot.illegal_moves, ["Aqua Jet"])
        self.assertIn("1 move flagged", [c.label for c in self.store.summary.checks])
        # megas use the base learnset
        self.store.set_form(1, "charizard-mega-y")
        self.assertEqual(self.store.slot(1).illegal_moves, ["Aqua Jet"])
        options = self.store.move_options(1)
        self.assertTrue(options.known)
        self.assertEqual([m.name for m in options.legal], ["Air Slash", "Flare Blitz", "Heat Wave", "Protect"])
        self.assertEqual([m.name for m in options.others], ["Anchor Shot", "Aqua Jet", "Last Respects"], "removed moves are never offered")

    def test_picker_hides_illegal_moves_unless_show_all(self):
        options = self.store.move_options(1)
        picked = []
        dialog = MovePickerDialog(species_label="Charizard", options=options, current="Heat Wave", show_all=False, on_pick=picked.append, on_close=lambda: None)
        names = [c.content.controls[2].value for c in dialog._list.controls if hasattr(c, "content") and hasattr(c.content, "controls") and len(c.content.controls) > 2]
        self.assertEqual(names, ["Air Slash", "Flare Blitz", "Heat Wave", "Protect"])
        self.assertIn("3 others hidden", dialog._caption.value)
        dialog._toggle_show_all(True)
        names = [c.content.controls[2].value for c in dialog._list.controls if hasattr(c, "content") and hasattr(c.content, "controls") and len(c.content.controls) > 2]
        self.assertEqual(names, ["Air Slash", "Flare Blitz", "Heat Wave", "Protect", "Anchor Shot", "Aqua Jet", "Last Respects"])
        dialog._search.value = "Grassy Glide"
        dialog._refresh()
        dialog._pick_first()
        self.assertEqual(picked, ["Grassy Glide"], "unknown names can be used as typed")
        serialise(dialog)

    def test_view_option_and_picker_flow(self):
        page = StubPage()
        ctx = AppContext(page, catalogs=self.catalogs)
        view = TeamView(ctx, self.store)
        view.ensure_loaded()
        self.assertFalse(view.show_all_moves)
        view._set_show_all_moves(True)
        self.assertTrue(view._show_all_moves_item.checked)
        view._open_move_picker(1, 0)
        dialog = page.dialogs[-1]
        self.assertIsInstance(dialog, MovePickerDialog)
        self.assertTrue(dialog._switch.value, "picker follows the team-builder option")
        dialog._on_pick("Aqua Jet")
        self.assertEqual(self.store.slot(1).moves[0].name, "Aqua Jet")
        self.assertFalse(self.store.slot(1).moves[0].legal)
        card = view.cards[0]
        self.assertTrue(card._moves[0]._warn.visible)
        self.assertIn("Champions learnset", card._moves[0].tooltip)
        serialise(view)



    def test_import_preview_flags_moves_outside_the_learnset(self):
        from pokemon_champions_planning_tool.ui.views.team.dialogs.import_dialog import ImportDialog

        page = StubPage()
        ctx = AppContext(page, catalogs=self.catalogs)
        paste = "Charizard @ Charcoal\nAbility: Blaze\n- Heat Wave\n- Aqua Jet\n- Knock Off\n- Protect\n"
        dialog = ImportDialog(ctx, self.store, initial_text=paste, initial_title="Sun")
        self.assertEqual(dialog.step, 1)
        row = dialog._preview.controls[0]
        chip_row = row.content.controls[1].controls[2]
        self.assertTrue(chip_row.visible)
        self.assertEqual(chip_row.controls[0]._label.value, "2 moves not in Champions learnset")
        self.assertEqual(chip_row.controls[0].tooltip, "Aqua Jet, Knock Off")
        serialise(dialog)



    def test_offensive_coverage_from_assigned_moves(self):
        self.store.set_move(1, 0, "Heat Wave")     # fire, special
        self.store.set_move(1, 1, "Protect")       # status: ignored
        slot = self.store.slot(1)
        self.assertEqual(slot.damaging_types, ["fire"])
        # variable-power moves (base power 0 in Showdown data) still count as damaging
        from pokemon_champions_planning_tool.domain.moves import MoveInfo as _MI
        from pokemon_champions_planning_tool.ui.views.team.summary import SlotMove as _SM
        probe = type(slot)(position=9)
        probe.moves = (_SM("Grass Knot", _MI("grassknot", "Grass Knot", "Grass", "Special", None, 100, 20, 0, "normal", None, True), True),)
        self.assertEqual(probe.damaging_types, ["grass"])
        self.assertEqual(slot.super_effective_against, ["grass", "ice", "bug", "steel"])
        summary = self.store.summary
        self.assertTrue(summary.has_moves)
        self.assertEqual(summary.offense["grass"][0], 2.0)
        self.assertIsNone(summary.offense["grass"][1], "empty slot has no moves")
        self.assertIn("water", summary.uncovered)
        self.assertNotIn("grass", summary.uncovered)
        self.assertTrue(any(c.label.endswith("uncovered") for c in summary.checks))
        page = StubPage()
        view = TeamView(AppContext(page, catalogs=self.catalogs), self.store)
        view.ensure_loaded()
        self.assertEqual(view.cards[0]._coverage_label.value, "Hits SE · 4")
        self.assertIn("Not hit super-effectively", view.summary._uncovered.value)
        serialise(view)


if __name__ == "__main__":
    unittest.main()
