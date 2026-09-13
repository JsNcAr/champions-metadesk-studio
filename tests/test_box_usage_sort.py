"""Unit tests for sorting Box Pokémon by tournament usage (regulation-aware)."""

import unittest
from datetime import datetime, timezone, timedelta

from sqlmodel import Session, SQLModel, create_engine

from pokemon_champions_planning_tool.domain.entities.box_entry import BoxEntry
from pokemon_champions_planning_tool.domain.entities.pokemon import Pokemon, PokemonStats
from pokemon_champions_planning_tool.infrastructure.database.models import (
    TournamentRecord,
    TournamentTeamRecord,
    TournamentTeamMemberRecord,
)
from pokemon_champions_planning_tool.infrastructure.database.repositories import TournamentRepository
from pokemon_champions_planning_tool.services.tournament_service import TournamentService
from pokemon_champions_planning_tool.ui.views.box.filters import BoxFilters, sort_entries
from pokemon_champions_planning_tool.ui.views.box.store import BoxStore
from pokemon_champions_planning_tool.ui.views.box.table import EXTRA_COLUMNS, BoxTable
from pokemon_champions_planning_tool.ui.views.box.card import PokemonCard


def _make_pokemon(
    name: str,
    cid: str,
    species_name: str | None = None,
    dex: int = 1,
    hp: int = 50,
) -> Pokemon:
    return Pokemon(
        canonical_id=cid,
        species_name=species_name or name.lower(),
        display_name=name,
        form_name="Mega" if "mega" in cid else "base",
        dex_number=dex,
        types=["fire"],
        stats=PokemonStats(hp=hp, attack=50, defense=50, special_attack=50, special_defense=50, speed=50),
    )


class TestTournamentUsageQueries(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = TournamentRepository(self.session)

        now = datetime.now(timezone.utc)
        # Create 3 tournaments: Reg M-A (old), Reg M-B (mid), Reg M-C (new), and a Singles tourney
        t_a = TournamentRecord(
            tournament_id="t-a",
            name="Tourney A",
            event_date=now - timedelta(days=60),
            format_regulation="Regulation M-A",
            game_platform="Pokémon Champions",
            battle_format="doubles",
        )
        t_b = TournamentRecord(
            tournament_id="t-b",
            name="Tourney B",
            event_date=now - timedelta(days=30),
            format_regulation="Regulation M-B",
            game_platform="Pokémon Champions",
            battle_format="doubles",
        )
        t_c = TournamentRecord(
            tournament_id="t-c",
            name="Tourney C",
            event_date=now - timedelta(days=2),
            format_regulation="Regulation M-C",
            game_platform="Pokémon Champions",
            battle_format="doubles",
        )
        t_singles = TournamentRecord(
            tournament_id="t-s",
            name="Singles Tourney",
            event_date=now - timedelta(days=1),
            format_regulation="Regulation M-C",
            game_platform="Pokémon Champions",
            battle_format="singles",
        )
        for t in (t_a, t_b, t_c, t_singles):
            self.repo.upsert_tournament(t)

        # Populate teams and members
        # Reg M-C doubles: Team 1 has Charizard (base) and Incineroar
        # Reg M-C doubles: Team 2 has Charizard-Mega-Y (base_cid=charizard) and Flutter Mane
        # Reg M-C singles: Team 3 has Pikachu
        # Reg M-B doubles: Team 4 has Charizard
        self._add_team("t-c", 1, [("charizard", None), ("incineroar", None)])
        self._add_team("t-c", 2, [("charizard-mega-y", "charizard"), ("flutter-mane", None)])
        self._add_team("t-s", 1, [("pikachu", None)])
        self._add_team("t-b", 1, [("charizard", None)])

    def _add_team(self, tournament_id: str, placement: int, members_data: list[tuple[str, str | None]]):
        team = TournamentTeamRecord(
            tournament_id=tournament_id,
            player_name=f"Player {placement}",
            placement=placement,
            standing_label=f"{placement}th",
            showdown_text="Charizard\n",
        )
        members = [
            TournamentTeamMemberRecord(
                slot_number=slot,
                canonical_id=cid,
                base_canonical_id=base_cid,
                species_name=cid.capitalize(),
            )
            for slot, (cid, base_cid) in enumerate(members_data, 1)
        ]
        self.repo.save_team(team, members)

    def tearDown(self):
        self.session.close()

    def test_get_latest_regulation(self):
        latest = self.repo.get_latest_regulation("Pokémon Champions")
        self.assertEqual(latest, "Regulation M-C")

    def test_list_regulations_by_date(self):
        regs = self.repo.list_regulations_by_date("Pokémon Champions")
        self.assertEqual(regs, ["Regulation M-C", "Regulation M-B", "Regulation M-A"])

    def test_species_usage_by_regulation_specific(self):
        # In Regulation M-C doubles:
        # Charizard base appears 1 time, Mega Y appears 1 time.
        # Both "charizard" and "charizard-mega-y" should be present.
        # "charizard" aggregates 2, "charizard-mega-y" is 1.
        usage = self.repo.species_usage_by_regulation(regulation="Regulation M-C", battle_format="doubles")
        self.assertEqual(usage.get("charizard"), 2)
        self.assertEqual(usage.get("charizard-mega-y"), 1)
        self.assertEqual(usage.get("incineroar"), 1)
        self.assertEqual(usage.get("flutter-mane"), 1)
        # Pikachu is in singles only, so it should not appear in doubles
        self.assertNotIn("pikachu", usage)

    def test_species_usage_by_regulation_all(self):
        usage = self.repo.species_usage_by_regulation(regulation=None, battle_format="doubles")
        # Charizard appeared in Reg M-B (1) and Reg M-C (2) -> total 3
        self.assertEqual(usage.get("charizard"), 3)

    def test_service_forwarding(self):
        svc = TournamentService(self.session)
        self.assertEqual(svc.get_latest_regulation(), "Regulation M-C")
        self.assertEqual(svc.list_regulations_by_date(), ["Regulation M-C", "Regulation M-B", "Regulation M-A"])
        usage = svc.species_usage_by_regulation("Regulation M-C", "doubles")
        self.assertEqual(usage.get("charizard"), 2)


class TestBoxUsageSort(unittest.TestCase):
    def setUp(self):
        p_char = _make_pokemon("Charizard", "charizard", dex=6)
        p_incin = _make_pokemon("Incineroar", "incineroar", dex=727)
        p_flutter = _make_pokemon("Flutter Mane", "flutter-mane", dex=987)
        p_pika = _make_pokemon("Pikachu", "pikachu", dex=25)

        self.entries = [
            BoxEntry(pokemon=p_pika),
            BoxEntry(pokemon=p_incin),
            BoxEntry(pokemon=p_flutter),
            BoxEntry(pokemon=p_char),
        ]
        self.usage_map = {
            "charizard": 100,
            "incineroar": 80,
            "flutter-mane": 80,
            "pikachu": 5,
        }

    def test_sort_entries_usage_descending(self):
        # Charizard (100) -> Flutter Mane (80, F < I) -> Incineroar (80, I > F) -> Pikachu (5)
        sorted_e = sort_entries(self.entries, key="usage", descending=True, usage_map=self.usage_map)
        names = [e.pokemon.display_name for e in sorted_e]
        self.assertEqual(names, ["Charizard", "Flutter Mane", "Incineroar", "Pikachu"])

    def test_sort_entries_usage_ascending(self):
        sorted_e = sort_entries(self.entries, key="usage", descending=False, usage_map=self.usage_map)
        names = [e.pokemon.display_name for e in sorted_e]
        self.assertEqual(names, ["Pikachu", "Flutter Mane", "Incineroar", "Charizard"])

    def test_sort_entries_mega_variant_fallback(self):
        p_mega = _make_pokemon("Charizard", "charizard-mega-y", species_name="charizard", dex=6)
        entries = [BoxEntry(pokemon=p_mega), BoxEntry(pokemon=_make_pokemon("Pikachu", "pikachu", dex=25))]
        # usage_map only has base "charizard": 50
        sorted_e = sort_entries(entries, key="usage", descending=True, usage_map={"charizard": 50, "pikachu": 10})
        self.assertEqual(sorted_e[0].pokemon.canonical_id, "charizard-mega-y")

    def test_box_filters_usage_regulation_serialization(self):
        f = BoxFilters(sort="usage", usage_regulation="Regulation M-B", descending=True)
        d = f.to_dict()
        self.assertEqual(d["usage_regulation"], "Regulation M-B")
        self.assertEqual(d["sort"], "usage")

        restored = BoxFilters.from_dict(d)
        self.assertEqual(restored.usage_regulation, "Regulation M-B")
        self.assertEqual(restored.sort, "usage")

        # cleared() preserves view preferences including sort and usage_regulation
        cleared = restored.cleared()
        self.assertEqual(cleared.usage_regulation, "Regulation M-B")
        self.assertEqual(cleared.sort, "usage")

    def test_box_filters_defaults(self):
        f = BoxFilters()
        self.assertEqual(f.usage_regulation, "latest")
        self.assertEqual(f.sort, "name")


class TestBoxStoreUsageCache(unittest.TestCase):
    def test_get_usage_map_caching_and_invalidation(self):
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        def session_factory():
            return Session(engine)

        store = BoxStore(session_factory=session_factory)
        # Seed a tournament
        with session_factory() as s:
            repo = TournamentRepository(s)
            t = TournamentRecord(
                tournament_id="t-1",
                name="Tourney",
                event_date=datetime.now(timezone.utc),
                format_regulation="Regulation M-C",
                game_platform="Pokémon Champions",
                battle_format="doubles",
            )
            repo.upsert_tournament(t)

        self.assertEqual(store.latest_regulation(), "Regulation M-C")
        self.assertEqual(store.available_regulations(), ["Regulation M-C"])

        umap1 = store.get_usage_map("latest")
        self.assertIsInstance(umap1, dict)
        self.assertIn(("Regulation M-C", "doubles"), store._usage_cache)

        # Invalidate
        store.invalidate_usage_cache()
        self.assertEqual(len(store._usage_cache), 0)


class TestTableAndCardUsageIntegration(unittest.TestCase):
    def test_extra_columns_contains_usage(self):
        self.assertIn("usage", EXTRA_COLUMNS)
        label, sort_key, numeric = EXTRA_COLUMNS["usage"]
        self.assertEqual(label, "Usage")
        self.assertEqual(sort_key, "usage")
        self.assertTrue(numeric)

    def test_table_extra_cells_usage(self):
        table = BoxTable(on_sort=lambda _k, _a: None, on_select=lambda _e: None)
        table.set_columns(["usage"])
        p = _make_pokemon("Charizard", "charizard")
        entry = BoxEntry(pokemon=p)
        table.update_from([entry], sort="usage", descending=True, selected_id=None, usage_map={"charizard": 1250})
        cells = table._extra_cells(entry)
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].content.value, "1,250")

    def test_card_caption_with_usage(self):
        card = PokemonCard(on_select=lambda _e: None, on_favorite=lambda _e, _f: None, on_tag=lambda _t: None)
        p = _make_pokemon("Charizard", "charizard", dex=6)
        entry = BoxEntry(pokemon=p)
        card.update_from(entry, selected=False, show_stats=False, mega_capable=False, usage_text="1,250 teams")
        self.assertIn("1,250 teams", card._form.value)
        self.assertIn("#006", card._form.value)


if __name__ == "__main__":
    unittest.main()
