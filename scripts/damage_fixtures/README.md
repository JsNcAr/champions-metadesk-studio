# Damage fixtures

Golden fixtures for `domain/damage/`, generated from the official Smogon damage calculator
(https://github.com/smogon/damage-calc, MIT), which ships a dedicated Pokémon Champions
mechanics module (`calc/src/mechanics/champions.ts`, generation number 0). The Python engine
is a port of that module; `tests/test_damage_fixtures.py` replays every case here and must
match roll for roll, including the description and KO text.

The published npm package (`@smogon/calc@0.11.0`) has no Champions data, so the generator
builds the calculator from source at the commit pinned in `CALC_COMMIT`.

```sh
export PATH=~/.config/nvm/versions/node/v22.22.0/bin:$PATH   # Node 22
cd scripts/damage_fixtures
npm run setup   # clones + compiles into .work/ (git-ignored)
npm run gen     # writes tests/fixtures/damage/*.json and _data.json
```

Fixtures are regenerated only when `CALC_COMMIT` changes; review the diff and update
`PORTED_CALC_COMMIT` in `domain/damage/__init__.py` in the same commit. Scenarios live in
`scenarios.mjs`; they enumerate every branch of the Champions module by category plus a
seeded random sweep, so a new mechanic gets a new scenario, not a hand-edited fixture.
