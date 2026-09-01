"""Box view backend: filters/sorting, the store, catalogues, and repository batch ops."""

import contextlib
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon
from pokemon_champions_planning_tool.domain.entities.pokemon_stats import PokemonStats
from pokemon_champions_planning_tool.domain.entities.team import Team
from pokemon_champions_planning_tool.domain.entities.team_member import TeamMember
from pokemon_champions_planning_tool.infrastructure.database.models import ChampionsSpeciesRecord, MegaEvolutionRecord
from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository, TeamRepository
from pokemon_champions_planning_tool.ui.catalogs import Catalogs
from pokemon_champions_planning_tool.ui.views.box import BoxFilters, BoxStore, apply_filters, sort_entries


def _mon(cid: str, name: str, types, hp=80, atk=80, dfn=80, spa=80, spd=80, spe=80, species=None) -> Pokemon:
    return Pokemon(
        canonical_id=cid, display_name=name, species_name=species or cid.split("-")[0], types=list(types),
        stats=PokemonStats(hp=hp, attack=atk, defense=dfn, sp_atk=spa, sp_def=spd, speed=spe),
    )


ENTRIES = [
    BoxEntry(pokemon=_mon("charizard", "Charizard", ["fire", "flying"], 78, 84, 78, 109, 85, 100), tags=["lead"], is_favorite=True),
    BoxEntry(pokemon=_mon("rillaboom", "Rillaboom", ["grass"], 100, 125, 90, 60, 70, 85), tags=["support"]),
    BoxEntry(pokemon=_mon("incineroar", "Incineroar", ["fire", "dark"], 95, 115, 90, 80, 90, 60)),
    BoxEntry(pokemon=_mon("ursaluna", "Ursaluna", ["ground", "normal"], 130, 140, 105, 45, 80, 50), is_planned=True),
]


class TestFilters(unittest.TestCase):
    def test_defaults_hide_planned_and_sort_by_name(self):
        out = apply_filters(ENTRIES, BoxFilters())
        self.assertEqual([e.pokemon.display_name for e in out], ["Charizard", "Incineroar", "Rillaboom"])

    def test_text_matches_name_tag_or_type(self):
        self.assertEqual({e.pokemon.canonical_id for e in apply_filters(ENTRIES, BoxFilters(text="fire"))}, {"charizard", "incineroar"})
        self.assertEqual([e.pokemon.canonical_id for e in apply_filters(ENTRIES, BoxFilters(text="supp"))], ["rillaboom"])
        self.assertEqual([e.pokemon.canonical_id for e in apply_filters(ENTRIES, BoxFilters(text="INCIN"))], ["incineroar"])

    def test_type_filter_is_any_of_and_ands_with_text(self):
        both = apply_filters(ENTRIES, BoxFilters(types=frozenset({"grass", "dark"})))
        self.assertEqual({e.pokemon.canonical_id for e in both}, {"rillaboom", "incineroar"})
        narrowed = apply_filters(ENTRIES, BoxFilters(types=frozenset({"fire"}), text="lead"))
        self.assertEqual([e.pokemon.canonical_id for e in narrowed], ["charizard"])

    def test_favourites_mega_planned_and_ranges(self):
        self.assertEqual([e.pokemon.canonical_id for e in apply_filters(ENTRIES, BoxFilters(favourites_only=True))], ["charizard"])
        megas = apply_filters(ENTRIES, BoxFilters(mega_capable_only=True), mega_species={"charizard"})
        self.assertEqual([e.pokemon.canonical_id for e in megas], ["charizard"])
        self.assertEqual(len(apply_filters(ENTRIES, BoxFilters(show_planned=True))), 4)
        self.assertEqual([e.pokemon.canonical_id for e in apply_filters(ENTRIES, BoxFilters(bst_range=(530, 560)))], ["charizard", "incineroar", "rillaboom"], "inclusive: both 530s match")
        self.assertEqual([e.pokemon.canonical_id for e in apply_filters(ENTRIES, BoxFilters(bst_range=(531, 560)))], ["charizard"])
        fast = apply_filters(ENTRIES, BoxFilters(stat_ranges={"speed": (90, 255)}))
        self.assertEqual([e.pokemon.canonical_id for e in fast], ["charizard"])
        tagged = apply_filters(ENTRIES, BoxFilters(tags=frozenset({"support"})))
        self.assertEqual([e.pokemon.canonical_id for e in tagged], ["rillaboom"])

    def test_sorting_every_key_both_directions(self):
        owned = [e for e in ENTRIES if not e.is_planned]
        self.assertEqual([e.pokemon.canonical_id for e in sort_entries(owned, "attack", True)], ["rillaboom", "incineroar", "charizard"])
        self.assertEqual([e.pokemon.canonical_id for e in sort_entries(owned, "speed", False)], ["incineroar", "rillaboom", "charizard"])
        self.assertEqual([e.pokemon.canonical_id for e in sort_entries(owned, "bst", True)][0], "charizard")
        for key in ("hp", "defense", "special_attack", "special_defense", "added", "name"):
            self.assertEqual(len(sort_entries(owned, key)), 3, key)

    def test_active_labels_and_removal(self):
        f = BoxFilters(text="x", types=frozenset({"fire"}), favourites_only=True, bst_range=(500, 600), stat_ranges={"speed": (100, 255)}, tags=frozenset({"lead"}))
        keys = [k for k, _ in f.active_labels()]
        self.assertEqual(keys, ["text", "type:fire", "favourites_only", "bst_range", "stat:speed", "tag:lead"])
        self.assertEqual(f.without("type:fire").types, frozenset())
        self.assertEqual(f.without("stat:speed").stat_ranges, {})
        self.assertEqual(f.without("bst_range").bst_range, BoxFilters().bst_range)
        cleared = f.cleared()
        self.assertFalse(cleared.is_active())
        self.assertEqual(BoxFilters(sort="speed", descending=True).cleared().sort, "speed", "sort is a view preference")


class _TempDb:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.engine = create_engine(f"sqlite:///{Path(self.dir) / 'box.db'}", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)

    @contextlib.contextmanager
    def session(self):
        with Session(self.engine) as s:
            yield s

    def close(self):
        self.engine.dispose()
        shutil.rmtree(self.dir)


class TestBoxStore(unittest.TestCase):
    def setUp(self):
        self.db = _TempDb()
        with self.db.session() as s:
            repo = BoxRepository(s)
            self.ids = {e.pokemon.canonical_id: repo.upsert_box_entry(e).box_entry_id for e in ENTRIES if not e.is_planned}
            self.ids["ursaluna"] = repo.create_planned_entry(ENTRIES[3]).box_entry_id
            s.add(MegaEvolutionRecord(canonical_id="charizard-mega-x", species_name="charizard", display_name="Mega Charizard X",
                                      types=["fire", "dragon"], hp=78, attack=130, defense=111, special_attack=130, special_defense=85, speed=100))
            s.add(ChampionsSpeciesRecord(entry_number=1, species_name="charizard", display_name="Charizard"))
            s.add(ChampionsSpeciesRecord(entry_number=2, species_name="chansey", display_name="Chansey"))
            s.commit()
            team = TeamRepository(s).create(Team(name="Sun"))
            TeamRepository(s).upsert_member(team.team_id, TeamMember(box_entry_id=self.ids["charizard"], slot_position=3))
        self.catalogs = Catalogs.load(self.db.session)
        self.store = BoxStore(self.catalogs, self.db.session)
        self.changes = []
        self.store.subscribe(self.changes.append)

    def tearDown(self):
        self.db.close()

    def test_load_visible_and_counts(self):
        self.store.load()
        self.assertEqual(self.changes, [("all",)])
        self.assertEqual(len(self.store.entries), 4, "planned entries are loaded but hidden by default")
        self.assertEqual([e.pokemon.display_name for e in self.store.visible()], ["Charizard", "Incineroar", "Rillaboom"])
        self.assertEqual(self.store.counts(), (3, 3))
        self.assertEqual(self.store.all_tags(), ["lead", "support"])
        self.assertTrue(self.store.is_mega_capable(self.store.entry(self.ids["charizard"])))

    def test_catalogs(self):
        self.assertEqual(self.catalogs.champions_names, ["Charizard", "Chansey"])
        self.assertEqual(self.catalogs.mega_species, frozenset({"charizard"}))
        self.assertEqual([r.display_name for r in self.catalogs.suggest_species("ch")], ["Charizard", "Chansey"])
        self.assertEqual([r.display_name for r in self.catalogs.suggest_species("ans")], ["Chansey"])
        self.assertEqual(self.catalogs.suggest_species("c"), [], "two characters minimum")

    def test_detail_has_forms_teams_and_defensive_buckets(self):
        self.store.load()
        detail = self.store.detail(self.ids["charizard"])
        self.assertEqual([f.label for f in detail.forms], ["Base", "Mega Charizard X"])
        self.assertEqual(detail.teams, (("Sun", 3),))
        self.assertEqual(detail.defensive_buckets()[4.0], ["rock"])
        self.assertEqual(detail.defensive_buckets("charizard-mega-x")[4.0], [], "Fire/Dragon has no 4× weakness")
        self.assertEqual(detail.form("charizard-mega-x").stats.attack, 130)

    def test_metadata_mutations_notify_per_entry(self):
        self.store.load()
        cid = self.ids["rillaboom"]
        self.store.set_favorite(cid, True)
        self.store.save_notes(cid, "Fake Out lead")
        self.store.save_tags(cid, [" Lead ", "lead", "support", ""])
        self.assertEqual(self.changes[1:], [("entry", cid)] * 3)
        with self.db.session() as s:
            fresh = BoxRepository(s).load_entry(str(cid))
        self.assertTrue(fresh.is_favorite)
        self.assertEqual(fresh.notes, "Fake Out lead")
        self.assertEqual(fresh.tags, ["Lead", "support"], "trimmed and de-duplicated case-insensitively")

    def test_delete_cascades_team_members_and_restore_brings_entry_back(self):
        self.store.load()
        self.store.select(self.ids["charizard"])
        removed = self.store.delete([self.ids["charizard"]])
        self.assertEqual([e.pokemon.display_name for e in removed], ["Charizard"])
        self.assertIsNone(self.store.selected_id)
        with self.db.session() as s:
            self.assertEqual(TeamRepository(s).teams_containing(self.ids["charizard"]), [])
            self.assertEqual(len(BoxRepository(s).list_entries()), 2)
        self.store.restore(removed)
        self.assertIn("Charizard", [e.pokemon.display_name for e in self.store.visible()])
        restored = next(e for e in self.store.entries if e.pokemon.canonical_id == "charizard")
        self.assertEqual(restored.tags, ["lead"])
        self.assertTrue(restored.is_favorite)

    def test_bulk_update(self):
        self.store.load()
        n = self.store.bulk_update([self.ids["rillaboom"], self.ids["incineroar"]], add_tags=["core"], is_favorite=True)
        self.assertEqual(n, 2)
        favs = [e.pokemon.canonical_id for e in self.store.visible() if e.is_favorite]
        self.assertEqual(sorted(favs), ["charizard", "incineroar", "rillaboom"])
        self.assertTrue(all("core" in e.tags for e in self.store.entries if e.pokemon.canonical_id in ("rillaboom", "incineroar")))

    def test_add_by_name_delegates_and_export_counts_owned_only(self):
        self.store.load()
        with patch("pokemon_champions_planning_tool.ui.views.box.store.add_pokemon_to_box", return_value=ENTRIES[0]) as add:
            self.assertIs(self.store.add_by_name("Charizard"), ENTRIES[0])
            add.assert_called_once_with("Charizard")
        with patch("pokemon_champions_planning_tool.ui.views.box.store.export_box_entries_to_csv") as export:
            self.assertEqual(self.store.export_csv(), 3)
            self.assertEqual(len(export.call_args.args[0]), 3)


if __name__ == "__main__":
    unittest.main()
