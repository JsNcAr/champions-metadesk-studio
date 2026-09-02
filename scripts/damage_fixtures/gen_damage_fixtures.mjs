// Golden fixture generator: runs every scenario through the Smogon calculator's Champions
// module (built from source in .work/ — see README.md) and writes tests/fixtures/damage/.
import {createRequire} from "node:module";
import {mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

import {scenarios} from "./scenarios.mjs";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const commit = readFileSync(join(here, "CALC_COMMIT"), "utf8").trim();
const calc = require(join(here, ".work", "damage-calc", "calc", "dist"));
const {calculate, Generations, Pokemon, Move, Field, MEGA_STONES, toID} = calc;

const gen = Generations.get(0);
if (!gen.abilities.get("megasol") || !gen.species.get("chandeluremega")) {
  throw new Error("The built calculator has no Pokémon Champions data — check CALC_COMMIT and rerun `npm run setup`.");
}

const OUT = join(here, "..", "..", "tests", "fixtures", "damage");
mkdirSync(OUT, {recursive: true});

const SIDE_KEYS = ["spikes", "isSR", "isReflect", "isLightScreen", "isProtected", "isSeeded", "isNightmared", "isSaltCured", "isCharge",
  "isTailwind", "isHelpingHand", "isPowerTrick", "isFriendGuard", "isAuroraVeil", "isSwitching"];

function side(spec = {}) {
  const s = {};
  for (const k of SIDE_KEYS) s[k] = k === "spikes" ? (spec.spikes || 0) : k === "isSwitching" ? (spec.isSwitching || null) : !!spec[k];
  return s;
}

function normMon(spec) {
  return {
    name: spec.name,
    ability: spec.ability ?? null,
    abilityOn: !!spec.abilityOn,
    item: spec.item ?? null,
    nature: spec.nature ?? null,
    points: spec.points || {},
    boosts: spec.boosts || {},
    curHP: spec.curHP ?? null,
    status: spec.status || "",
    toxicCounter: spec.toxicCounter || 0,
    alliesFainted: spec.alliesFainted || 0,
    gender: spec.gender ?? null,
  };
}

function buildPokemon(m) {
  const species = gen.species.get(toID(m.name));
  if (!species) throw new Error(`unknown species ${m.name}`);
  const opts = {evs: m.points, boosts: m.boosts, abilityOn: m.abilityOn, status: m.status, toxicCounter: m.toxicCounter, alliesFainted: m.alliesFainted};
  if (m.ability) opts.ability = m.ability;
  if (m.item) opts.item = m.item;
  if (m.nature) opts.nature = m.nature;
  if (m.curHP !== null) opts.curHP = m.curHP;
  if (m.gender) opts.gender = m.gender;
  return new Pokemon(gen, m.name, opts);
}

function normMove(spec) {
  return {name: spec.name, isCrit: !!spec.isCrit, hits: spec.hits ?? null, timesUsed: spec.timesUsed || 1, timesUsedWithMetronome: spec.timesUsedWithMetronome || 1};
}

function normField(spec = {}) {
  return {
    gameType: spec.gameType || "Singles",
    weather: spec.weather ?? null,
    terrain: spec.terrain ?? null,
    isGravity: !!spec.isGravity,
    isMagicRoom: !!spec.isMagicRoom,
    isWonderRoom: !!spec.isWonderRoom,
    isFairyAura: !!spec.isFairyAura,
    isDarkAura: !!spec.isDarkAura,
    attackerSide: side(spec.attackerSide),
    defenderSide: side(spec.defenderSide),
  };
}

function safe(fn) {
  try {
    return fn();
  } catch (e) {
    return {__error__: String(e.message || e)};
  }
}

function plain(obj) {
  return JSON.parse(JSON.stringify(obj));
}

const usedMoves = new Map();
const usedSpecies = new Map();

function runCase(spec) {
  const attacker = normMon(spec.attacker);
  const defender = normMon(spec.defender);
  const move = normMove(spec.move);
  const field = normField(spec.field);
  const moveData = gen.moves.get(toID(move.name));
  if (!moveData) throw new Error(`unknown move ${move.name}`);
  const a = buildPokemon(attacker);
  const d = buildPokemon(defender);
  const mOpts = {isCrit: move.isCrit, timesUsed: move.timesUsed, timesUsedWithMetronome: move.timesUsedWithMetronome, ability: a.ability};
  if (move.hits !== null) mOpts.hits = move.hits;
  const m = new Move(gen, move.name, mOpts);
  const f = new Field(field);
  const r = calculate(gen, a, d, m, f);
  usedMoves.set(moveData.id, plain(moveData));
  usedSpecies.set(a.species.id, plain(a.species));
  usedSpecies.set(d.species.id, plain(d.species));
  return {
    id: spec.id,
    tags: spec.tags || [],
    attacker, defender, move, field,
    data: {
      attacker: {name: a.species.name, types: a.types, baseStats: a.species.baseStats, weightkg: a.weightkg, gender: a.gender, abilities: a.species.abilities || {}},
      defender: {name: d.species.name, types: d.types, baseStats: d.species.baseStats, weightkg: d.weightkg, gender: d.gender, abilities: d.species.abilities || {}},
      move: plain(moveData),
    },
    expected: {
      damage: r.damage,
      desc: safe(() => r.desc()),
      moveDesc: safe(() => r.moveDesc()),
      kochance: safe(() => r.kochance()),
      recoil: safe(() => r.recoil()),
      recovery: safe(() => r.recovery()),
      rawDesc: plain(r.rawDesc),
      attackerStats: r.attacker.stats, attackerRaw: r.attacker.rawStats, attackerBoosts: r.attacker.boosts, attackerAbility: r.attacker.ability ?? null,
      defenderStats: r.defender.stats, defenderRaw: r.defender.rawStats, defenderBoosts: r.defender.boosts, defenderAbility: r.defender.ability ?? null,
      moveType: r.move.type, moveBp: r.move.bp, moveCategory: r.move.category, moveTarget: r.move.target, moveHits: r.move.hits,
      attackerMaxHP: r.attacker.maxHP(), attackerCurHP: r.attacker.curHP(), defenderMaxHP: r.defender.maxHP(), defenderCurHP: r.defender.curHP(),
    },
  };
}

const byCategory = new Map();
let skipped = 0;
for (const spec of scenarios()) {
  const category = spec.id.split(".")[0];
  try {
    const out = runCase(spec);
    if (!byCategory.has(category)) byCategory.set(category, []);
    byCategory.get(category).push(out);
  } catch (e) {
    skipped++;
    console.warn(`skip ${spec.id}: ${e.message}`);
  }
}

let total = 0;
for (const [category, cases] of byCategory) {
  const meta = {schema: 1, calc_commit: commit, node: process.version, gen: 0, category, count: cases.length};
  const body = `{"meta": ${JSON.stringify(meta)},\n "cases": [\n${cases.map((c) => "  " + JSON.stringify(c)).join(",\n")}\n ]}\n`;
  writeFileSync(join(OUT, `${category}.json`), body);
  total += cases.length;
}

const items = [...gen.items].map((i) => plain(i));
const abilities = [...gen.abilities].map((a) => a.name);
const natures = [...gen.natures].map((n) => plain(n));
const data = {
  meta: {schema: 1, calc_commit: commit, node: process.version, gen: 0},
  items, abilities, natures,
  mega_stones: MEGA_STONES,
  moves: Object.fromEntries([...usedMoves.entries()].sort()),
  species: Object.fromEntries([...usedSpecies.entries()].sort()),
  species_names: [...gen.species].map((s) => s.name),
};
writeFileSync(join(OUT, "_data.json"), JSON.stringify(data, null, 1) + "\n");
console.log(`wrote ${total} cases in ${byCategory.size} categories (${skipped} skipped) to ${OUT}`);
