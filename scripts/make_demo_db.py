"""Build a demo database for screenshots and demos, from real data.

    poetry run python scripts/make_demo_db.py            # into demo/ (gitignored)
    poetry run python scripts/make_demo_db.py --out /tmp/demo --skip-tournaments

Then run the app on it:

    PCPT_DATABASE=demo/pokemon_champions.db PCPT_ASSETS_DIR=demo/assets \\
        poetry run python -m pokemon_champions_planning_tool.main --web

It goes through the app's own services, so the result is exactly what a user would have:

1. the catalogues (species, moves, learnsets, items, Mega Evolutions) from Pokémon Showdown
   and PokéAPI;
2. a box of real Champions Pokémon with a few tags, favourites and notes;
3. two teams imported from Showdown pastes, as the Teams view's import does;
4. one tournament sync from Limitless and Victory Road, so Meta has real events;
5. the sprites of every Champions species in the demo's sprite cache. The web build can
   only show cached sprites (the Showdown CDN is blocked by the page's cross-origin
   policy), so without this every Pokémon would show a Poké Ball.

Needs network access and takes a few minutes, mostly the tournament sync. Rerunning it
rebuilds the database from scratch.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BOX = """\
Garchomp #Sand #Core ★
Incineroar #Support ★
Kingambit #Core
Charizard #Sun
Venusaur #Sun
Tyranitar #Sand
Excadrill #Sand
Talonflame #Speed-control
Primarina
Annihilape
Greninja
Sylveon
Milotic
Gholdengo #Core ★
Archaludon
Pelipper #Rain
Froslass
Aerodactyl
Whimsicott #Speed-control
Dragonite
"""

NOTES = {
    "Garchomp": "Scarf or Clear Amulet? Try both in Calc",
    "Incineroar": "Fake Out + Intimidate glue",
}

TEAMS = {
    "Sand Balance": """\
Tyranitar @ Tyranitarite
Ability: Sand Stream
Level: 50
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Rock Slide
- Knock Off
- Low Kick
- Protect

Excadrill @ Life Orb
Ability: Sand Rush
Level: 50
EVs: 4 HP / 252 Atk / 252 Spe
Jolly Nature
- High Horsepower
- Iron Head
- Rock Slide
- Protect

Garchomp @ Clear Amulet
Ability: Rough Skin
Level: 50
EVs: 4 HP / 252 Atk / 252 Spe
Jolly Nature
- Earthquake
- Dragon Claw
- Stomping Tantrum
- Protect

Incineroar @ Sitrus Berry
Ability: Intimidate
Level: 50
EVs: 252 HP / 4 Atk / 252 SpD
Careful Nature
- Fake Out
- Flare Blitz
- Knock Off
- Parting Shot

Primarina @ Throat Spray
Ability: Liquid Voice
Level: 50
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Hyper Voice
- Moonblast
- Ice Beam
- Protect

Whimsicott @ Focus Sash
Ability: Prankster
Level: 50
EVs: 4 HP / 252 SpA / 252 Spe
Timid Nature
- Tailwind
- Moonblast
- Encore
- Protect
""",
    "Sun Offense": """\
Charizard @ Charizardite Y
Ability: Blaze
Level: 50
EVs: 4 HP / 252 SpA / 252 Spe
Timid Nature
- Heat Wave
- Solar Beam
- Air Slash
- Protect

Venusaur @ Leftovers
Ability: Chlorophyll
Level: 50
EVs: 4 HP / 252 SpA / 252 Spe
Modest Nature
- Leaf Storm
- Sludge Bomb
- Sleep Powder
- Protect

Kingambit @ Black Glasses
Ability: Defiant
Level: 50
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Kowtow Cleave
- Iron Head
- Sucker Punch
- Protect

Gholdengo @ Choice Specs
Ability: Good as Gold
Level: 50
EVs: 4 HP / 252 SpA / 252 Spe
Modest Nature
- Make It Rain
- Shadow Ball
- Focus Blast
- Trick

Talonflame @ Sharp Beak
Ability: Gale Wings
Level: 50
EVs: 4 HP / 252 Atk / 252 Spe
Jolly Nature
- Brave Bird
- Flare Blitz
- Tailwind
- Protect

Sylveon @ Throat Spray
Ability: Pixilate
Level: 50
EVs: 252 HP / 252 SpA / 4 SpD
Modest Nature
- Hyper Voice
- Moonblast
- Quick Attack
- Protect
""",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT / "demo"), help="output folder (default: demo/)")
    parser.add_argument("--skip-tournaments", action="store_true", help="no tournament sync (fast, offline-ish)")
    parser.add_argument("--skip-sprites", action="store_true", help="do not download sprites")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    db = out / "pokemon_champions.db"
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    (out / "preferences.json").unlink(missing_ok=True)
    # Read by config at import time: set before importing the app.
    os.environ["PCPT_DATABASE"] = str(db)
    os.environ["PCPT_ASSETS_DIR"] = str(out / "assets")
    sys.path.insert(0, str(ROOT / "src"))

    from pokemon_champions_planning_tool.infrastructure.database.database import get_session, initialize_database
    from pokemon_champions_planning_tool.infrastructure.database.repositories import BoxRepository
    from pokemon_champions_planning_tool.main import bootstrap_catalogues, prepare_sprite_cache_dir, refresh_catalogues
    from pokemon_champions_planning_tool.services.box_transfer_service import apply_box_import, parse_box_import_text
    from pokemon_champions_planning_tool.services.showdown_service import commit_team_import, parse_showdown_text
    from pokemon_champions_planning_tool.ui.catalogs import Catalogs

    started = time.perf_counter()
    print(f"Building {db}")
    initialize_database()

    print("1/5 Catalogues (Showdown, PokéAPI)…")
    with get_session() as session:
        bootstrap_catalogues(session)
        refresh_catalogues(session)
    catalogs = Catalogs.load()
    legal = {name.lower() for name in catalogs.champions_species_names}
    print(f"    {len(catalogs.species_by_canonical):,} species, {len(legal):,} in Champions")

    print("2/5 Box…")
    lines = [line for line in BOX.splitlines() if line.strip()]
    kept = [line for line in lines if not legal or line.split("#")[0].split("★")[0].strip().lower() in legal]
    for line in sorted(set(lines) - set(kept)):
        print(f"    skipped (not in Champions): {line}")
    items = parse_box_import_text("\n".join(kept)).items
    for item in items:
        item.notes = NOTES.get(item.species, item.notes)
    with get_session() as session:
        report = apply_box_import(session, items)
    print(f"    {report.added} added")

    print("3/5 Teams…")
    for name, paste in TEAMS.items():
        with get_session() as session:
            result = commit_team_import(session, parse_showdown_text(paste), use_planned=False, team_name=name,
                                        legal_species=catalogs.champions_species_names or None)
        print(f"    {name}: {len(result.created_owned)} new, {len(result.reused)} from the box, {len(result.created_planned)} planned")

    if args.skip_tournaments:
        print("4/5 Tournaments: skipped")
    else:
        print("4/5 Tournaments (Limitless, Victory Road; a few minutes)…")
        from pokemon_champions_planning_tool.services.tournament_sync_service import sync_tournaments

        last = [0.0]

        def progress(p) -> None:
            if time.perf_counter() - last[0] > 5:
                last[0] = time.perf_counter()
                print(f"    {getattr(p, 'message', p)}")

        with get_session() as session:
            result = sync_tournaments(session, max_age_days=365, include_official=True, on_progress=progress)
        print(f"    done: {result.get('status', 'ok')}")

    if args.skip_sprites:
        print("5/5 Sprites: skipped")
    else:
        print("5/5 Sprites…")
        from pokemon_champions_planning_tool.domain.pokemon_identity import get_pokemon_sprite_url, get_showdown_sprite_slug
        from pokemon_champions_planning_tool.services.sprite_cache_service import sprite_cache

        prepare_sprite_cache_dir()
        with get_session() as session:
            ids = {e.pokemon.canonical_id for e in BoxRepository(session).list_entries(include_planned=True)}
        ids |= {s.canonical_id for s in catalogs.species_by_canonical.values() if s.is_legal}
        jobs = []
        for cid in sorted(ids):
            slug = get_showdown_sprite_slug(cid)
            if slug and not sprite_cache.is_cached(f"{slug}.png"):
                jobs.append((get_pokemon_sprite_url(cid), f"{slug}.png"))
        with ThreadPoolExecutor(max_workers=8) as pool:
            fetched = sum(1 for ok in pool.map(lambda job: _download(sprite_cache, *job), jobs) if ok)
        print(f"    {fetched} of {len(jobs)} downloaded into {sprite_cache.cache_dir}")

    print(f"Done in {time.perf_counter() - started:.0f} s. Run the app on it with:")
    print(f"    PCPT_DATABASE={db} PCPT_ASSETS_DIR={out / 'assets'} poetry run python -m pokemon_champions_planning_tool.main --web")
    return 0


def _download(cache, url: str, filename: str) -> bool:
    try:
        return cache.download_sprite_sync(url, filename)
    except Exception:  # noqa: BLE001 - a missing sprite is not worth stopping for
        return False


if __name__ == "__main__":
    sys.exit(main())
