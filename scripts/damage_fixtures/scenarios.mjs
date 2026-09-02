// Scenario catalogue for the golden fixtures. Every branch of the Champions module gets an
// explicit case; a seeded random sweep at the end covers combinations. Species, moves, items
// and abilities are calculator names (the generator validates species and moves).

const cases = [];
const counters = new Map();

function add(category, name, spec) {
  const n = (counters.get(category) || 0) + 1;
  counters.set(category, n);
  cases.push({id: `${category}.${name}.${String(n).padStart(3, "0")}`, tags: spec.tags || [category], ...spec});
}

const mon = (name, o = {}) => ({name, ...o});
const P = {phys: {atk: 32, spe: 32, hp: 2}, spec: {spa: 32, spe: 32, hp: 2}, bulk: {hp: 32, def: 32, spd: 2}, sbulk: {hp: 32, spd: 32, def: 2}, none: {}};

const DOUBLES = {gameType: "Doubles"};

// ---------------------------------------------------------------- baseline
function baseline() {
  const c = "baseline";
  add(c, "stab_single", {attacker: mon("Kingambit", {nature: "Adamant", points: P.phys}), defender: mon("Incineroar", {nature: "Impish", points: P.bulk}), move: {name: "Kowtow Cleave"}});
  add(c, "no_stab", {attacker: mon("Kingambit", {nature: "Adamant", points: P.phys}), defender: mon("Incineroar", {nature: "Impish", points: P.bulk}), move: {name: "Iron Head"}});
  add(c, "dual_type_se", {attacker: mon("Garchomp", {nature: "Jolly", points: P.phys}), defender: mon("Charizard"), move: {name: "Stone Edge"}});
  add(c, "quad_weak", {attacker: mon("Garchomp", {nature: "Jolly", points: P.phys}), defender: mon("Charizard"), move: {name: "Rock Slide"}});
  add(c, "quad_resist", {attacker: mon("Charizard", {nature: "Timid", points: P.spec}), defender: mon("Archaludon"), move: {name: "Air Slash"}});
  add(c, "immune", {attacker: mon("Garchomp"), defender: mon("Charizard"), move: {name: "Earthquake"}});
  add(c, "status_move", {attacker: mon("Vileplume"), defender: mon("Garchomp"), move: {name: "Spore"}});
  add(c, "spread_doubles", {attacker: mon("Garchomp", {points: P.phys}), defender: mon("Kingambit"), move: {name: "Earthquake"}, field: DOUBLES});
  add(c, "spread_singles", {attacker: mon("Garchomp", {points: P.phys}), defender: mon("Kingambit"), move: {name: "Earthquake"}});
  add(c, "all_adjacent_foes_doubles", {attacker: mon("Charizard", {nature: "Modest", points: P.spec}), defender: mon("Vileplume"), move: {name: "Heat Wave"}, field: DOUBLES});
  add(c, "single_target_doubles", {attacker: mon("Charizard", {nature: "Modest", points: P.spec}), defender: mon("Vileplume"), move: {name: "Flamethrower"}, field: DOUBLES});
  add(c, "neutral_nature_no_points", {attacker: mon("Raichu"), defender: mon("Gengar"), move: {name: "Thunderbolt"}});
  add(c, "hindered_nature", {attacker: mon("Raichu", {nature: "Modest", points: P.phys}), defender: mon("Gengar", {nature: "Bold", points: P.bulk}), move: {name: "Volt Tackle"}});
  add(c, "zero_bp_variable", {attacker: mon("Metagross"), defender: mon("Raichu"), move: {name: "Body Slam"}});
  add(c, "mega_attacker", {attacker: mon("Metagross-Mega", {nature: "Jolly", points: P.phys}), defender: mon("Gardevoir-Mega", {nature: "Timid", points: P.spec}), move: {name: "Iron Head"}});
  add(c, "max_boosts", {attacker: mon("Kingambit", {boosts: {atk: 6}}), defender: mon("Incineroar", {boosts: {def: -6}}), move: {name: "Kowtow Cleave"}});
  add(c, "min_boosts", {attacker: mon("Kingambit", {boosts: {atk: -6}}), defender: mon("Incineroar", {boosts: {def: 6}}), move: {name: "Kowtow Cleave"}});
  for (const b of [-3, -1, 1, 2, 3]) {
    add(c, `atk_boost_${b}`, {attacker: mon("Charizard", {boosts: {spa: b}}), defender: mon("Meganium", {boosts: {spd: -b}}), move: {name: "Flamethrower"}});
  }
}

// ---------------------------------------------------------------- weather
function weather() {
  const c = "weather";
  const fire = mon("Charizard", {nature: "Modest", points: P.spec});
  const water = mon("Swampert", {nature: "Modest", points: P.spec});
  for (const w of ["Sun", "Rain", "Sand", "Snow", null]) {
    add(c, `fire_${w}`, {attacker: fire, defender: mon("Meganium"), move: {name: "Flamethrower"}, field: {weather: w}});
    add(c, `water_${w}`, {attacker: water, defender: mon("Charizard"), move: {name: "Surf"}, field: {weather: w}});
    add(c, `weather_ball_${w}`, {attacker: mon("Pelipper", {nature: "Modest", points: P.spec}), defender: mon("Garchomp"), move: {name: "Weather Ball"}, field: {weather: w}});
    add(c, `solar_beam_${w}`, {attacker: mon("Meganium", {nature: "Modest"}), defender: mon("Swampert"), move: {name: "Solar Beam"}, field: {weather: w}});
  }
  add(c, "sand_spd_rock", {attacker: fire, defender: mon("Tyranitar"), move: {name: "Flamethrower"}, field: {weather: "Sand"}});
  add(c, "sand_def_rock_physical", {attacker: mon("Kingambit"), defender: mon("Tyranitar"), move: {name: "Iron Head"}, field: {weather: "Sand"}});
  add(c, "snow_def_ice", {attacker: mon("Kingambit"), defender: mon("Weavile"), move: {name: "Iron Head"}, field: {weather: "Snow"}});
  add(c, "snow_spd_ice_special", {attacker: fire, defender: mon("Weavile"), move: {name: "Flamethrower"}, field: {weather: "Snow"}});
  add(c, "air_lock", {attacker: fire, defender: mon("Meganium", {ability: "Cloud Nine"}), move: {name: "Flamethrower"}, field: {weather: "Sun"}});
  add(c, "air_lock_attacker", {attacker: mon("Charizard", {ability: "Air Lock"}), defender: mon("Meganium"), move: {name: "Flamethrower"}, field: {weather: "Rain"}});
  add(c, "mega_sol_fire", {attacker: mon("Charizard", {ability: "Mega Sol"}), defender: mon("Meganium"), move: {name: "Flamethrower"}});
  add(c, "mega_sol_water", {attacker: mon("Swampert", {ability: "Mega Sol"}), defender: mon("Charizard"), move: {name: "Surf"}});
  add(c, "mega_sol_weather_ball", {attacker: mon("Pelipper", {ability: "Mega Sol"}), defender: mon("Garchomp"), move: {name: "Weather Ball"}});
  add(c, "mega_sol_solar_beam_in_rain", {attacker: mon("Meganium", {ability: "Mega Sol"}), defender: mon("Swampert"), move: {name: "Solar Beam"}, field: {weather: "Rain"}});
  add(c, "mega_sol_ignores_sand_spd", {attacker: mon("Charizard", {ability: "Mega Sol"}), defender: mon("Tyranitar"), move: {name: "Flamethrower"}, field: {weather: "Sand"}});
  add(c, "mega_sol_defender_rain_water", {attacker: water, defender: mon("Charizard", {ability: "Mega Sol"}), move: {name: "Surf"}, field: {weather: "Rain"}});
  add(c, "castform_forecast_sun", {attacker: mon("Castform", {ability: "Forecast"}), defender: mon("Meganium"), move: {name: "Weather Ball"}, field: {weather: "Sun"}});
  add(c, "castform_forecast_rain_def", {attacker: mon("Charizard"), defender: mon("Castform", {ability: "Forecast"}), move: {name: "Flamethrower"}, field: {weather: "Rain"}});
  add(c, "solar_power", {attacker: mon("Charizard", {ability: "Solar Power"}), defender: mon("Meganium"), move: {name: "Air Slash"}, field: {weather: "Sun"}});
  add(c, "solar_power_physical", {attacker: mon("Charizard", {ability: "Solar Power"}), defender: mon("Meganium"), move: {name: "Flare Blitz"}, field: {weather: "Sun"}});
  add(c, "drought_mega_y", {attacker: mon("Charizard-Mega-Y", {nature: "Timid", points: P.spec}), defender: mon("Garchomp", {nature: "Jolly", points: {hp: 32, atk: 32, spe: 2}, item: "Leftovers"}), move: {name: "Heat Wave"}, field: {...DOUBLES, weather: "Sun"}});
}

// ---------------------------------------------------------------- terrain
function terrain() {
  const c = "terrain";
  for (const t of ["Electric", "Grassy", "Psychic", "Misty", null]) {
    add(c, `electric_move_${t}`, {attacker: mon("Raichu", {nature: "Timid", points: P.spec}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}, field: {terrain: t}});
    add(c, `grass_move_${t}`, {attacker: mon("Meganium", {points: P.phys}), defender: mon("Swampert"), move: {name: "Wood Hammer"}, field: {terrain: t}});
    add(c, `psychic_move_${t}`, {attacker: mon("Gardevoir", {points: P.spec}), defender: mon("Vileplume"), move: {name: "Psychic"}, field: {terrain: t}});
    add(c, `dragon_move_${t}`, {attacker: mon("Garchomp", {points: P.phys}), defender: mon("Dragonite"), move: {name: "Dragon Claw"}, field: {terrain: t}});
    add(c, `terrain_pulse_${t}`, {attacker: mon("Gardevoir", {points: P.spec}), defender: mon("Vileplume"), move: {name: "Terrain Pulse"}, field: {terrain: t}});
    add(c, `rising_voltage_${t}`, {attacker: mon("Raichu", {points: P.spec}), defender: mon("Pelipper"), move: {name: "Rising Voltage"}, field: {terrain: t}});
    add(c, `expanding_force_${t}`, {attacker: mon("Gardevoir", {points: P.spec}), defender: mon("Vileplume"), move: {name: "Expanding Force"}, field: {...DOUBLES, terrain: t}});
    add(c, `misty_explosion_${t}`, {attacker: mon("Gardevoir"), defender: mon("Garchomp"), move: {name: "Misty Explosion"}, field: {terrain: t}});
  }
  add(c, "grassy_earthquake", {attacker: mon("Garchomp", {points: P.phys}), defender: mon("Kingambit"), move: {name: "Earthquake"}, field: {terrain: "Grassy"}});
  add(c, "grassy_bulldoze", {attacker: mon("Garchomp"), defender: mon("Kingambit"), move: {name: "Bulldoze"}, field: {terrain: "Grassy"}});
  add(c, "grassy_earthquake_vs_flying", {attacker: mon("Garchomp"), defender: mon("Charizard"), move: {name: "Earthquake"}, field: {terrain: "Grassy"}});
  add(c, "electric_flying_attacker_not_grounded", {attacker: mon("Charizard"), defender: mon("Pelipper"), move: {name: "Thunder Punch"}, field: {terrain: "Electric"}});
  add(c, "electric_levitate_not_grounded", {attacker: mon("Rotom-Wash", {points: P.spec}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}, field: {terrain: "Electric"}});
  add(c, "electric_eelevate_not_grounded", {attacker: mon("Raichu", {ability: "Eelevate"}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}, field: {terrain: "Electric"}});
  add(c, "electric_gravity_grounds", {attacker: mon("Charizard"), defender: mon("Pelipper"), move: {name: "Thunder Punch"}, field: {terrain: "Electric", isGravity: true}});
  add(c, "electric_iron_ball_grounds", {attacker: mon("Charizard", {item: "Iron Ball"}), defender: mon("Pelipper"), move: {name: "Thunder Punch"}, field: {terrain: "Electric"}});
  add(c, "misty_dragon_vs_levitate", {attacker: mon("Garchomp"), defender: mon("Rotom-Wash"), move: {name: "Dragon Claw"}, field: {terrain: "Misty"}});
  add(c, "psychic_priority_blocked", {attacker: mon("Kingambit"), defender: mon("Garchomp"), move: {name: "Sucker Punch"}, field: {terrain: "Psychic"}});
  add(c, "psychic_priority_vs_flying", {attacker: mon("Kingambit"), defender: mon("Charizard"), move: {name: "Sucker Punch"}, field: {terrain: "Psychic"}});
  add(c, "grav_apple", {attacker: mon("Appletun"), defender: mon("Swampert"), move: {name: "Grav Apple"}, field: {isGravity: true}});
  add(c, "gravity_ground_vs_flying", {attacker: mon("Garchomp"), defender: mon("Charizard"), move: {name: "Earthquake"}, field: {isGravity: true}});
  add(c, "steel_roller_no_terrain", {attacker: mon("Kingambit"), defender: mon("Gardevoir"), move: {name: "Steel Roller"}});
  add(c, "steel_roller_terrain", {attacker: mon("Kingambit"), defender: mon("Gardevoir"), move: {name: "Steel Roller"}, field: {terrain: "Psychic"}});
}

// ---------------------------------------------------------------- screens
function screens() {
  const c = "screens";
  const phys = {attacker: mon("Kingambit", {points: P.phys}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}};
  const spec = {attacker: mon("Gengar", {points: P.spec}), defender: mon("Incineroar"), move: {name: "Shadow Ball"}};
  for (const [label, sideSpec] of [["reflect", {isReflect: true}], ["light_screen", {isLightScreen: true}], ["aurora_veil", {isAuroraVeil: true}], ["reflect_and_veil", {isReflect: true, isAuroraVeil: true}], ["both_screens", {isReflect: true, isLightScreen: true}]]) {
    for (const gt of ["Singles", "Doubles"]) {
      add(c, `${label}_phys_${gt}`, {...phys, field: {gameType: gt, defenderSide: sideSpec}});
      add(c, `${label}_spec_${gt}`, {...spec, field: {gameType: gt, defenderSide: sideSpec}});
    }
  }
  add(c, "reflect_crit_ignores", {...phys, move: {name: "Kowtow Cleave", isCrit: true}, field: {defenderSide: {isReflect: true}}});
  add(c, "veil_crit_ignores", {...spec, move: {name: "Shadow Ball", isCrit: true}, field: {defenderSide: {isAuroraVeil: true}}});
  add(c, "infiltrator", {...spec, attacker: mon("Gengar", {ability: "Infiltrator", points: P.spec}), field: {defenderSide: {isLightScreen: true, isReflect: true}}});
  add(c, "brick_break", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Brick Break"}, field: {defenderSide: {isReflect: true}}});
  add(c, "psychic_fangs", {attacker: mon("Garchomp"), defender: mon("Incineroar"), move: {name: "Psychic Fangs"}, field: {defenderSide: {isReflect: true, isLightScreen: true}}});
  add(c, "raging_bull_combat", {attacker: mon("Tauros-Paldea-Combat"), defender: mon("Incineroar"), move: {name: "Raging Bull"}, field: {defenderSide: {isReflect: true}}});
  add(c, "raging_bull_blaze", {attacker: mon("Tauros-Paldea-Blaze"), defender: mon("Meganium"), move: {name: "Raging Bull"}});
  add(c, "raging_bull_aqua", {attacker: mon("Tauros-Paldea-Aqua"), defender: mon("Charizard"), move: {name: "Raging Bull"}});
  add(c, "attacker_side_screen_irrelevant", {...phys, field: {attackerSide: {isReflect: true}}});
}

// ---------------------------------------------------------------- crit
function crit() {
  const c = "crit";
  add(c, "plain", {attacker: mon("Kingambit", {points: P.phys}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "will_crit_frost_breath", {attacker: mon("Weavile"), defender: mon("Garchomp"), move: {name: "Frost Breath"}});
  add(c, "merciless_vs_poison", {attacker: mon("Kingambit", {ability: "Merciless"}), defender: mon("Incineroar", {status: "psn"}), move: {name: "Kowtow Cleave"}});
  add(c, "merciless_vs_toxic", {attacker: mon("Kingambit", {ability: "Merciless"}), defender: mon("Incineroar", {status: "tox"}), move: {name: "Kowtow Cleave"}});
  add(c, "merciless_no_status", {attacker: mon("Kingambit", {ability: "Merciless"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "shell_armor_blocks", {attacker: mon("Kingambit"), defender: mon("Incineroar", {ability: "Shell Armor"}), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "battle_armor_blocks", {attacker: mon("Kingambit"), defender: mon("Incineroar", {ability: "Battle Armor"}), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "sniper", {attacker: mon("Kingambit", {ability: "Sniper"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "sniper_no_crit", {attacker: mon("Kingambit", {ability: "Sniper"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "ignores_negative_atk_boost", {attacker: mon("Kingambit", {boosts: {atk: -2}}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "keeps_positive_atk_boost", {attacker: mon("Kingambit", {boosts: {atk: 2}}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "ignores_positive_def_boost", {attacker: mon("Kingambit"), defender: mon("Incineroar", {boosts: {def: 2}}), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "keeps_negative_def_boost", {attacker: mon("Kingambit"), defender: mon("Incineroar", {boosts: {def: -2}}), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "spread_crit_doubles", {attacker: mon("Garchomp"), defender: mon("Kingambit"), move: {name: "Earthquake", isCrit: true}, field: DOUBLES});
}

// ---------------------------------------------------------------- status
function status() {
  const c = "status";
  add(c, "burn_physical", {attacker: mon("Kingambit", {status: "brn"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "burn_special", {attacker: mon("Gengar", {status: "brn"}), defender: mon("Incineroar"), move: {name: "Shadow Ball"}});
  add(c, "burn_guts", {attacker: mon("Kingambit", {ability: "Guts", status: "brn"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "guts_paralysis", {attacker: mon("Kingambit", {ability: "Guts", status: "par"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "guts_special_no_boost", {attacker: mon("Gengar", {ability: "Guts", status: "psn"}), defender: mon("Incineroar"), move: {name: "Shadow Ball"}});
  add(c, "facade_burn", {attacker: mon("Kingambit", {status: "brn"}), defender: mon("Incineroar"), move: {name: "Facade"}});
  add(c, "facade_poison", {attacker: mon("Kingambit", {status: "psn"}), defender: mon("Incineroar"), move: {name: "Facade"}});
  add(c, "facade_paralysis", {attacker: mon("Kingambit", {status: "par"}), defender: mon("Incineroar"), move: {name: "Facade"}});
  add(c, "facade_no_status", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Facade"}});
  add(c, "marvel_scale", {attacker: mon("Kingambit"), defender: mon("Milotic", {ability: "Marvel Scale", status: "par"}), move: {name: "Kowtow Cleave"}});
  add(c, "marvel_scale_special", {attacker: mon("Gengar"), defender: mon("Milotic", {ability: "Marvel Scale", status: "par"}), move: {name: "Shadow Ball"}});
  add(c, "hex_status", {attacker: mon("Gengar"), defender: mon("Incineroar", {status: "brn"}), move: {name: "Hex"}});
  add(c, "hex_no_status", {attacker: mon("Gengar"), defender: mon("Incineroar"), move: {name: "Hex"}});
  add(c, "infernal_parade", {attacker: mon("Chandelure"), defender: mon("Incineroar", {status: "slp"}), move: {name: "Infernal Parade"}});
  add(c, "barb_barrage_poison", {attacker: mon("Overqwil"), defender: mon("Incineroar", {status: "psn"}), move: {name: "Barb Barrage"}});
  add(c, "barb_barrage_burn", {attacker: mon("Overqwil"), defender: mon("Incineroar", {status: "brn"}), move: {name: "Barb Barrage"}});
  add(c, "venoshock", {attacker: mon("Gengar"), defender: mon("Incineroar", {status: "tox"}), move: {name: "Venoshock"}});
  add(c, "quick_feet_electro_ball", {attacker: mon("Raichu", {ability: "Quick Feet", status: "par"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}});
  add(c, "paralysis_speed_gyro_ball", {attacker: mon("Metagross"), defender: mon("Raichu", {status: "par"}), move: {name: "Gyro Ball"}});
  add(c, "toxic_boost_like_flare_boost", {attacker: mon("Chandelure", {ability: "Flare Boost", status: "brn"}), defender: mon("Incineroar"), move: {name: "Shadow Ball"}});
}

// ---------------------------------------------------------------- hp scaling
function hpScaling() {
  const c = "hp_scaling";
  for (const hp of [100, 75, 50, 34, 33, 25, 12, 5, 1]) {
    add(c, `eruption_${hp}pct`, {attacker: mon("Torkoal", {nature: "Modest", points: P.spec, curHP: Math.max(1, Math.floor(170 * hp / 100))}), defender: mon("Meganium"), move: {name: "Eruption"}});
    add(c, `flail_${hp}pct`, {attacker: mon("Kingambit", {curHP: Math.max(1, Math.floor(175 * hp / 100))}), defender: mon("Incineroar"), move: {name: "Flail"}});
    add(c, `reversal_${hp}pct`, {attacker: mon("Lucario", {curHP: Math.max(1, Math.floor(145 * hp / 100))}), defender: mon("Incineroar"), move: {name: "Reversal"}});
    add(c, `hard_press_${hp}pct`, {attacker: mon("Archaludon"), defender: mon("Incineroar", {curHP: Math.max(1, Math.floor(170 * hp / 100))}), move: {name: "Hard Press"}});
    add(c, `blaze_${hp}pct`, {attacker: mon("Charizard", {ability: "Blaze", curHP: Math.max(1, Math.floor(153 * hp / 100))}), defender: mon("Meganium"), move: {name: "Flamethrower"}});
  }
  add(c, "water_spout", {attacker: mon("Milotic", {curHP: 100}), defender: mon("Charizard"), move: {name: "Water Spout"}});
  add(c, "overgrow_pinch", {attacker: mon("Meganium", {ability: "Overgrow", curHP: 40}), defender: mon("Swampert"), move: {name: "Wood Hammer"}});
  add(c, "torrent_pinch", {attacker: mon("Swampert", {ability: "Torrent", curHP: 40}), defender: mon("Charizard"), move: {name: "Surf"}});
  add(c, "swarm_pinch", {attacker: mon("Scizor", {ability: "Swarm", curHP: 30}), defender: mon("Gardevoir"), move: {name: "U-turn"}});
  add(c, "pain_split", {attacker: mon("Gengar", {curHP: 40}), defender: mon("Incineroar"), move: {name: "Pain Split"}});
  add(c, "pain_split_healthy_attacker", {attacker: mon("Gengar"), defender: mon("Incineroar", {curHP: 20}), move: {name: "Pain Split"}});
  add(c, "final_gambit", {attacker: mon("Lucario", {points: {hp: 32}}), defender: mon("Incineroar"), move: {name: "Final Gambit"}});
  add(c, "final_gambit_damaged", {attacker: mon("Lucario", {curHP: 60}), defender: mon("Incineroar"), move: {name: "Final Gambit"}});
  add(c, "multiscale_full", {attacker: mon("Kingambit"), defender: mon("Dragonite", {ability: "Multiscale"}), move: {name: "Iron Head"}});
  add(c, "multiscale_damaged", {attacker: mon("Kingambit"), defender: mon("Dragonite", {ability: "Multiscale", curHP: 150}), move: {name: "Iron Head"}});
  add(c, "gale_wings_full", {attacker: mon("Talonflame", {ability: "Gale Wings"}), defender: mon("Meganium"), move: {name: "Brave Bird"}});
  add(c, "gale_wings_damaged", {attacker: mon("Talonflame", {ability: "Gale Wings", curHP: 100}), defender: mon("Meganium"), move: {name: "Brave Bird"}});
}

// ---------------------------------------------------------------- weight
function weight() {
  const c = "weight";
  const targets = ["Pikachu", "Raichu", "Gardevoir", "Charizard", "Garchomp", "Kingambit", "Metagross", "Archaludon", "Hippowdon", "Tyranitar"];
  for (const t of targets) {
    add(c, `low_kick_${t}`, {attacker: mon("Lucario"), defender: mon(t), move: {name: "Low Kick"}});
    add(c, `grass_knot_${t}`, {attacker: mon("Meganium"), defender: mon(t), move: {name: "Grass Knot"}});
    add(c, `heavy_slam_metagross_${t}`, {attacker: mon("Metagross"), defender: mon(t), move: {name: "Heavy Slam"}});
    add(c, `heat_crash_torkoal_${t}`, {attacker: mon("Torkoal"), defender: mon(t), move: {name: "Heat Crash"}});
  }
  add(c, "heavy_metal_attacker", {attacker: mon("Metagross", {ability: "Heavy Metal"}), defender: mon("Garchomp"), move: {name: "Heavy Slam"}});
  add(c, "heavy_metal_defender_low_kick", {attacker: mon("Lucario"), defender: mon("Gardevoir", {ability: "Heavy Metal"}), move: {name: "Low Kick"}});
  add(c, "light_metal_attacker", {attacker: mon("Metagross", {ability: "Light Metal"}), defender: mon("Garchomp"), move: {name: "Heavy Slam"}});
  add(c, "light_metal_defender_grass_knot", {attacker: mon("Meganium"), defender: mon("Tyranitar", {ability: "Light Metal"}), move: {name: "Grass Knot"}});
  add(c, "heavy_slam_vs_heavy_metal", {attacker: mon("Metagross"), defender: mon("Kingambit", {ability: "Heavy Metal"}), move: {name: "Heavy Slam"}});
  add(c, "aggron_mega_heavy_metal", {attacker: mon("Aggron-Mega", {ability: "Heavy Metal"}), defender: mon("Raichu"), move: {name: "Heavy Slam"}});
  add(c, "heat_crash_mega_charizard_y", {attacker: mon("Charizard-Mega-Y"), defender: mon("Pikachu"), move: {name: "Heat Crash"}});
}

// ---------------------------------------------------------------- stat overrides
function statOverrides() {
  const c = "stat_overrides";
  add(c, "body_press", {attacker: mon("Archaludon", {points: {def: 32, hp: 32}}), defender: mon("Kingambit"), move: {name: "Body Press"}});
  add(c, "body_press_def_boost", {attacker: mon("Archaludon", {boosts: {def: 2, atk: -2}}), defender: mon("Kingambit"), move: {name: "Body Press"}});
  add(c, "body_press_wonder_room", {attacker: mon("Archaludon", {points: {def: 32}}), defender: mon("Kingambit"), move: {name: "Body Press"}, field: {isWonderRoom: true}});
  add(c, "body_press_power_trick", {attacker: mon("Archaludon", {points: {atk: 32}}), defender: mon("Kingambit"), move: {name: "Body Press"}, field: {attackerSide: {isPowerTrick: true}}});
  add(c, "foul_play", {attacker: mon("Incineroar"), defender: mon("Kingambit", {nature: "Adamant", points: P.phys}), move: {name: "Foul Play"}});
  add(c, "foul_play_defender_boost", {attacker: mon("Incineroar"), defender: mon("Kingambit", {boosts: {atk: 2}}), move: {name: "Foul Play"}});
  add(c, "foul_play_attacker_boost_ignored", {attacker: mon("Incineroar", {boosts: {atk: 6}}), defender: mon("Kingambit"), move: {name: "Foul Play"}});
  add(c, "psyshock", {attacker: mon("Gardevoir", {points: P.spec}), defender: mon("Audino", {points: {spd: 32, hp: 32}}), move: {name: "Psyshock"}});
  add(c, "psyshock_def_boost", {attacker: mon("Gardevoir"), defender: mon("Audino", {boosts: {def: 2}}), move: {name: "Psyshock"}});
  add(c, "psyshock_sand_no_spd_boost", {attacker: mon("Gardevoir"), defender: mon("Tyranitar"), move: {name: "Psyshock"}, field: {weather: "Sand"}});
  add(c, "psyshock_reflect", {attacker: mon("Gardevoir"), defender: mon("Audino"), move: {name: "Psyshock"}, field: {defenderSide: {isReflect: true}}});
  add(c, "psyshock_light_screen", {attacker: mon("Gardevoir"), defender: mon("Audino"), move: {name: "Psyshock"}, field: {defenderSide: {isLightScreen: true}}});
  add(c, "power_trick_attacker", {attacker: mon("Bastiodon", {points: {def: 32}}), defender: mon("Kingambit"), move: {name: "Rock Slide"}, field: {attackerSide: {isPowerTrick: true}}});
  add(c, "power_trick_defender", {attacker: mon("Kingambit"), defender: mon("Bastiodon"), move: {name: "Iron Head"}, field: {defenderSide: {isPowerTrick: true}}});
  add(c, "wonder_room_physical", {attacker: mon("Kingambit"), defender: mon("Audino"), move: {name: "Iron Head"}, field: {isWonderRoom: true}});
  add(c, "wonder_room_special", {attacker: mon("Gengar"), defender: mon("Audino"), move: {name: "Shadow Ball"}, field: {isWonderRoom: true}});
  add(c, "unaware_defender", {attacker: mon("Kingambit", {boosts: {atk: 4}}), defender: mon("Avalugg", {ability: "Unaware"}), move: {name: "Kowtow Cleave"}});
  add(c, "unaware_attacker", {attacker: mon("Avalugg", {ability: "Unaware"}), defender: mon("Kingambit", {boosts: {def: 4}}), move: {name: "Wave Crash"}});
  add(c, "unaware_foul_play", {attacker: mon("Avalugg", {ability: "Unaware"}), defender: mon("Kingambit", {boosts: {atk: 2}}), move: {name: "Foul Play"}});
  add(c, "unaware_vs_unaware", {attacker: mon("Avalugg", {ability: "Unaware", boosts: {atk: 2}}), defender: mon("Avalugg", {ability: "Unaware", boosts: {def: 2}}), move: {name: "Wave Crash"}});
  add(c, "hustle", {attacker: mon("Dragonite", {ability: "Hustle", points: P.phys}), defender: mon("Incineroar"), move: {name: "Dragon Claw"}});
  add(c, "hustle_special_no_boost", {attacker: mon("Dragonite", {ability: "Hustle"}), defender: mon("Incineroar"), move: {name: "Hurricane"}});
  add(c, "meteor_beam", {attacker: mon("Glimmora", {points: P.spec}), defender: mon("Charizard"), move: {name: "Meteor Beam"}});
  add(c, "meteor_beam_contrary", {attacker: mon("Glimmora", {ability: "Contrary"}), defender: mon("Charizard"), move: {name: "Meteor Beam"}});
  add(c, "electro_shot", {attacker: mon("Archaludon", {points: P.spec}), defender: mon("Pelipper"), move: {name: "Electro Shot"}});
  add(c, "shell_side_arm_physical", {attacker: mon("Slowbro", {points: {atk: 32}}), defender: mon("Audino", {points: {spd: 32}}), move: {name: "Shell Side Arm"}});
  add(c, "shell_side_arm_special", {attacker: mon("Slowbro", {points: {spa: 32}}), defender: mon("Kingambit"), move: {name: "Shell Side Arm"}});
}

// ---------------------------------------------------------------- knock off
function knockOff() {
  const c = "knock_off";
  const a = mon("Kingambit", {points: P.phys});
  add(c, "no_item", {attacker: a, defender: mon("Incineroar"), move: {name: "Knock Off"}});
  add(c, "with_item", {attacker: a, defender: mon("Incineroar", {item: "Sitrus Berry"}), move: {name: "Knock Off"}});
  add(c, "matching_mega_stone", {attacker: a, defender: mon("Charizard", {item: "Charizardite Y"}), move: {name: "Knock Off"}});
  add(c, "matching_mega_stone_on_mega", {attacker: a, defender: mon("Charizard-Mega-Y", {item: "Charizardite Y"}), move: {name: "Knock Off"}});
  add(c, "other_species_mega_stone", {attacker: a, defender: mon("Incineroar", {item: "Charizardite Y"}), move: {name: "Knock Off"}});
  add(c, "sticky_hold_second_hit", {attacker: mon("Kingambit", {ability: "Parental Bond"}), defender: mon("Incineroar", {ability: "Sticky Hold", item: "Sitrus Berry"}), move: {name: "Knock Off"}});
  add(c, "parental_bond_second_hit_resisted", {attacker: mon("Kingambit", {ability: "Parental Bond"}), defender: mon("Incineroar", {item: "Sitrus Berry"}), move: {name: "Knock Off"}});
  add(c, "klutz_disabled_item", {attacker: a, defender: mon("Incineroar", {ability: "Klutz", item: "Sitrus Berry"}), move: {name: "Knock Off"}});
  add(c, "magic_room", {attacker: a, defender: mon("Incineroar", {item: "Sitrus Berry"}), move: {name: "Knock Off"}, field: {isMagicRoom: true}});
  add(c, "poltergeist_no_item", {attacker: mon("Gengar"), defender: mon("Incineroar"), move: {name: "Poltergeist"}});
  add(c, "poltergeist_item", {attacker: mon("Gengar"), defender: mon("Incineroar", {item: "Leftovers"}), move: {name: "Poltergeist"}});
  add(c, "acrobatics_no_item", {attacker: mon("Talonflame"), defender: mon("Meganium"), move: {name: "Acrobatics"}});
  add(c, "acrobatics_item", {attacker: mon("Talonflame", {item: "Sharp Beak"}), defender: mon("Meganium"), move: {name: "Acrobatics"}});
  add(c, "fling_iron_ball", {attacker: mon("Kingambit", {item: "Iron Ball"}), defender: mon("Incineroar"), move: {name: "Fling"}});
  add(c, "fling_berry", {attacker: mon("Kingambit", {item: "Sitrus Berry"}), defender: mon("Incineroar"), move: {name: "Fling"}});
  add(c, "fling_hard_stone", {attacker: mon("Kingambit", {item: "Hard Stone"}), defender: mon("Incineroar"), move: {name: "Fling"}});
  add(c, "fling_mega_stone", {attacker: mon("Kingambit", {item: "Charizardite Y"}), defender: mon("Incineroar"), move: {name: "Fling"}});
  add(c, "fling_no_item", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Fling"}});
}

// ---------------------------------------------------------------- ability BP mods
function abilityBp() {
  const c = "ability_bp";
  add(c, "technician_60", {attacker: mon("Scizor", {ability: "Technician"}), defender: mon("Gardevoir"), move: {name: "Bullet Punch"}});
  add(c, "technician_61_no_boost", {attacker: mon("Scizor", {ability: "Technician"}), defender: mon("Gardevoir"), move: {name: "Aerial Ace"}});
  add(c, "technician_custom_bp_low_kick", {attacker: mon("Scizor-Mega", {ability: "Technician"}), defender: mon("Pikachu"), move: {name: "Low Kick"}});
  add(c, "technician_custom_bp_low_kick_heavy", {attacker: mon("Scizor-Mega", {ability: "Technician"}), defender: mon("Metagross"), move: {name: "Low Kick"}});
  add(c, "technician_weather_ball_doubled", {attacker: mon("Scizor", {ability: "Technician"}), defender: mon("Garchomp"), move: {name: "Weather Ball"}, field: {weather: "Rain"}});
  add(c, "sheer_force_secondary", {attacker: mon("Feraligatr", {ability: "Sheer Force"}), defender: mon("Gardevoir"), move: {name: "Ice Punch"}});
  add(c, "sheer_force_no_secondary", {attacker: mon("Feraligatr", {ability: "Sheer Force"}), defender: mon("Gardevoir"), move: {name: "Surf"}});
  add(c, "sheer_force_electro_shot", {attacker: mon("Archaludon", {ability: "Sheer Force"}), defender: mon("Pelipper"), move: {name: "Electro Shot"}});
  add(c, "sheer_force_freeze_dry_champions_no_secondary", {attacker: mon("Weavile", {ability: "Sheer Force"}), defender: mon("Swampert"), move: {name: "Freeze-Dry"}});
  add(c, "tough_claws_contact", {attacker: mon("Charizard-Mega-X", {ability: "Tough Claws"}), defender: mon("Meganium"), move: {name: "Flare Blitz"}});
  add(c, "tough_claws_no_contact", {attacker: mon("Charizard-Mega-X", {ability: "Tough Claws"}), defender: mon("Meganium"), move: {name: "Flamethrower"}});
  add(c, "sharpness", {attacker: mon("Gallade", {ability: "Sharpness"}), defender: mon("Incineroar"), move: {name: "Sacred Sword"}});
  add(c, "sharpness_crush_claw_champions_flag", {attacker: mon("Gallade", {ability: "Sharpness"}), defender: mon("Incineroar"), move: {name: "Crush Claw"}});
  add(c, "strong_jaw", {attacker: mon("Tyrantrum", {ability: "Strong Jaw"}), defender: mon("Incineroar"), move: {name: "Crunch"}});
  add(c, "mega_launcher", {attacker: mon("Clawitzer", {ability: "Mega Launcher"}), defender: mon("Incineroar"), move: {name: "Water Pulse"}});
  add(c, "iron_fist", {attacker: mon("Lucario", {ability: "Iron Fist"}), defender: mon("Incineroar"), move: {name: "Close Combat"}});
  add(c, "iron_fist_punch", {attacker: mon("Lucario", {ability: "Iron Fist"}), defender: mon("Incineroar"), move: {name: "Drain Punch"}});
  add(c, "reckless_recoil", {attacker: mon("Talonflame", {ability: "Reckless"}), defender: mon("Meganium"), move: {name: "Brave Bird"}});
  add(c, "reckless_crash", {attacker: mon("Lucario", {ability: "Reckless"}), defender: mon("Incineroar"), move: {name: "High Jump Kick"}});
  add(c, "reckless_no_recoil", {attacker: mon("Lucario", {ability: "Reckless"}), defender: mon("Incineroar"), move: {name: "Close Combat"}});
  add(c, "analytic_faster_no_boost", {attacker: mon("Raichu", {ability: "Analytic", points: P.spec}), defender: mon("Metagross"), move: {name: "Thunderbolt"}});
  add(c, "analytic_slower", {attacker: mon("Metagross", {ability: "Analytic"}), defender: mon("Raichu"), move: {name: "Psychic"}});
  add(c, "analytic_switching_out", {attacker: mon("Raichu", {ability: "Analytic", points: P.spec}), defender: mon("Metagross"), move: {name: "Thunderbolt"}, field: {defenderSide: {isSwitching: "out"}}});
  add(c, "analytic_ability_on", {attacker: mon("Raichu", {ability: "Analytic", abilityOn: true, points: P.spec}), defender: mon("Metagross"), move: {name: "Thunderbolt"}});
  add(c, "sand_force_rock", {attacker: mon("Excadrill", {ability: "Sand Force"}), defender: mon("Charizard"), move: {name: "Rock Slide"}, field: {weather: "Sand"}});
  add(c, "sand_force_steel", {attacker: mon("Excadrill", {ability: "Sand Force"}), defender: mon("Gardevoir"), move: {name: "Iron Head"}, field: {weather: "Sand"}});
  add(c, "sand_force_ground_no_sand", {attacker: mon("Excadrill", {ability: "Sand Force"}), defender: mon("Kingambit"), move: {name: "Earthquake"}});
  add(c, "sand_force_normal_in_sand", {attacker: mon("Excadrill", {ability: "Sand Force"}), defender: mon("Kingambit"), move: {name: "Body Slam"}, field: {weather: "Sand"}});
  add(c, "rivalry_same_gender", {attacker: mon("Luxray", {ability: "Rivalry", gender: "M"}), defender: mon("Incineroar", {gender: "M"}), move: {name: "Wild Charge"}});
  add(c, "rivalry_opposite_gender", {attacker: mon("Luxray", {ability: "Rivalry", gender: "M"}), defender: mon("Incineroar", {gender: "F"}), move: {name: "Wild Charge"}});
  add(c, "rivalry_genderless", {attacker: mon("Luxray", {ability: "Rivalry", gender: "M"}), defender: mon("Metagross"), move: {name: "Wild Charge"}});
  for (let n = 0; n <= 6; n++) {
    add(c, `supreme_overlord_${n}`, {attacker: mon("Kingambit", {ability: "Supreme Overlord", alliesFainted: n, points: P.phys}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  }
  add(c, "fairy_aura_attacker", {attacker: mon("Floette-Eternal", {ability: "Fairy Aura"}), defender: mon("Garchomp"), move: {name: "Moonblast"}});
  add(c, "fairy_aura_defender", {attacker: mon("Gardevoir"), defender: mon("Floette-Eternal", {ability: "Fairy Aura"}), move: {name: "Moonblast"}});
  add(c, "fairy_aura_field", {attacker: mon("Gardevoir"), defender: mon("Garchomp"), move: {name: "Moonblast"}, field: {isFairyAura: true}});
  add(c, "dark_aura_field", {attacker: mon("Kingambit"), defender: mon("Gardevoir"), move: {name: "Kowtow Cleave"}, field: {isDarkAura: true}});
  add(c, "dark_aura_field_wrong_type", {attacker: mon("Kingambit"), defender: mon("Gardevoir"), move: {name: "Iron Head"}, field: {isDarkAura: true}});
  add(c, "dry_skin_fire_bp", {attacker: mon("Charizard"), defender: mon("Toxicroak", {ability: "Dry Skin"}), move: {name: "Flamethrower"}});
  add(c, "helping_hand", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}, field: {...DOUBLES, attackerSide: {isHelpingHand: true}}});
  add(c, "charge_electric", {attacker: mon("Raichu"), defender: mon("Pelipper"), move: {name: "Thunderbolt"}, field: {attackerSide: {isCharge: true}}});
  add(c, "charge_non_electric", {attacker: mon("Raichu"), defender: mon("Pelipper"), move: {name: "Surf"}, field: {attackerSide: {isCharge: true}}});
  add(c, "electromorphosis_on", {attacker: mon("Raichu", {ability: "Electromorphosis", abilityOn: true}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}});
  add(c, "electromorphosis_off", {attacker: mon("Raichu", {ability: "Electromorphosis"}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}});
  add(c, "lash_out_dropped", {attacker: mon("Kingambit", {boosts: {atk: -1}}), defender: mon("Gardevoir"), move: {name: "Lash Out"}});
  add(c, "lash_out_no_drop", {attacker: mon("Kingambit"), defender: mon("Gardevoir"), move: {name: "Lash Out"}});
  add(c, "stored_power", {attacker: mon("Gardevoir", {boosts: {spa: 2, spe: 1, def: 1}}), defender: mon("Incineroar"), move: {name: "Stored Power"}});
  add(c, "stored_power_negative_ignored", {attacker: mon("Gardevoir", {boosts: {spa: -2}}), defender: mon("Incineroar"), move: {name: "Stored Power"}});
  add(c, "power_trip", {attacker: mon("Kingambit", {boosts: {atk: 3}}), defender: mon("Gardevoir"), move: {name: "Power Trip"}});
  add(c, "payback_slower", {attacker: mon("Metagross"), defender: mon("Raichu"), move: {name: "Payback"}});
  add(c, "payback_faster", {attacker: mon("Raichu"), defender: mon("Metagross"), move: {name: "Payback"}});
  add(c, "assurance", {attacker: mon("Kingambit"), defender: mon("Gardevoir"), move: {name: "Assurance"}});
  add(c, "assurance_parental_bond", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Gardevoir"), move: {name: "Assurance"}});
}

// ---------------------------------------------------------------- -ate abilities
function ate() {
  const c = "ate";
  for (const [ability, user] of [["Aerilate", "Dragonite-Mega"], ["Pixilate", "Sylveon"], ["Refrigerate", "Glalie-Mega"], ["Dragonize", "Dragonite"]]) {
    add(c, `${ability}_normal_move`, {attacker: mon(user, {ability}), defender: mon("Incineroar"), move: {name: "Body Slam"}});
    add(c, `${ability}_normal_special`, {attacker: mon(user, {ability}), defender: mon("Incineroar"), move: {name: "Hyper Voice"}});
    add(c, `${ability}_non_normal`, {attacker: mon(user, {ability}), defender: mon("Incineroar"), move: {name: "Earthquake"}});
    add(c, `${ability}_weather_ball_excluded`, {attacker: mon(user, {ability}), defender: mon("Incineroar"), move: {name: "Weather Ball"}});
    add(c, `${ability}_struggle_excluded`, {attacker: mon(user, {ability}), defender: mon("Incineroar"), move: {name: "Struggle"}});
    add(c, `${ability}_vs_immune_ghost`, {attacker: mon(user, {ability}), defender: mon("Gengar"), move: {name: "Body Slam"}});
  }
  add(c, "liquid_voice_sound", {attacker: mon("Primarina", {ability: "Liquid Voice"}), defender: mon("Charizard"), move: {name: "Hyper Voice"}});
  add(c, "liquid_voice_non_sound", {attacker: mon("Primarina", {ability: "Liquid Voice"}), defender: mon("Charizard"), move: {name: "Body Slam"}});
  add(c, "liquid_voice_vs_soundproof", {attacker: mon("Primarina", {ability: "Liquid Voice"}), defender: mon("Charizard", {ability: "Soundproof"}), move: {name: "Hyper Voice"}});
  add(c, "pixilate_vs_water_absorb_irrelevant", {attacker: mon("Sylveon", {ability: "Pixilate"}), defender: mon("Swampert", {ability: "Water Absorb"}), move: {name: "Hyper Voice"}});
  add(c, "protean_stab", {attacker: mon("Greninja", {ability: "Protean"}), defender: mon("Incineroar"), move: {name: "Ice Beam"}});
  add(c, "adaptability_stab", {attacker: mon("Basculegion", {ability: "Adaptability"}), defender: mon("Incineroar"), move: {name: "Wave Crash"}});
  add(c, "adaptability_no_stab", {attacker: mon("Basculegion", {ability: "Adaptability"}), defender: mon("Incineroar"), move: {name: "Ice Beam"}});
  add(c, "scrappy_ghost", {attacker: mon("Lopunny-Mega", {ability: "Scrappy"}), defender: mon("Gengar"), move: {name: "Body Slam"}});
  add(c, "scrappy_fighting_ghost", {attacker: mon("Lopunny-Mega", {ability: "Scrappy"}), defender: mon("Gengar"), move: {name: "High Jump Kick"}});
  add(c, "normalize_absent_in_champions_struggle_typeless", {attacker: mon("Kingambit"), defender: mon("Gengar"), move: {name: "Struggle"}});
}

// ---------------------------------------------------------------- attack / defense mods
function attackDefense() {
  const c = "attack_defense";
  add(c, "huge_power", {attacker: mon("Azumarill", {ability: "Huge Power"}), defender: mon("Incineroar"), move: {name: "Play Rough"}});
  add(c, "huge_power_special_no_boost", {attacker: mon("Azumarill", {ability: "Huge Power"}), defender: mon("Incineroar"), move: {name: "Surf"}});
  add(c, "pure_power", {attacker: mon("Medicham-Mega", {ability: "Pure Power"}), defender: mon("Incineroar"), move: {name: "High Jump Kick"}});
  add(c, "plus_on", {attacker: mon("Raichu", {ability: "Plus", abilityOn: true}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}});
  add(c, "plus_off", {attacker: mon("Raichu", {ability: "Plus"}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}});
  add(c, "minus_on_physical_no_boost", {attacker: mon("Raichu", {ability: "Minus", abilityOn: true}), defender: mon("Pelipper"), move: {name: "Volt Tackle"}});
  add(c, "flash_fire_on", {attacker: mon("Chandelure", {ability: "Flash Fire", abilityOn: true}), defender: mon("Meganium"), move: {name: "Flamethrower"}});
  add(c, "flash_fire_off", {attacker: mon("Chandelure", {ability: "Flash Fire"}), defender: mon("Meganium"), move: {name: "Flamethrower"}});
  add(c, "flash_fire_on_non_fire", {attacker: mon("Chandelure", {ability: "Flash Fire", abilityOn: true}), defender: mon("Meganium"), move: {name: "Shadow Ball"}});
  add(c, "fire_mane", {attacker: mon("Arcanine", {ability: "Fire Mane"}), defender: mon("Meganium"), move: {name: "Flare Blitz"}});
  add(c, "fire_mane_special", {attacker: mon("Arcanine", {ability: "Fire Mane"}), defender: mon("Meganium"), move: {name: "Flamethrower"}});
  add(c, "water_bubble_attacker", {attacker: mon("Araquanid", {ability: "Water Bubble"}), defender: mon("Charizard"), move: {name: "Liquidation"}});
  add(c, "water_bubble_defender", {attacker: mon("Charizard"), defender: mon("Araquanid", {ability: "Water Bubble"}), move: {name: "Flamethrower"}});
  add(c, "thick_fat_fire", {attacker: mon("Charizard"), defender: mon("Snorlax", {ability: "Thick Fat"}), move: {name: "Flamethrower"}});
  add(c, "thick_fat_ice", {attacker: mon("Weavile"), defender: mon("Snorlax", {ability: "Thick Fat"}), move: {name: "Ice Punch"}});
  add(c, "thick_fat_other", {attacker: mon("Kingambit"), defender: mon("Snorlax", {ability: "Thick Fat"}), move: {name: "Iron Head"}});
  add(c, "heatproof", {attacker: mon("Charizard"), defender: mon("Forretress", {ability: "Heatproof"}), move: {name: "Flamethrower"}});
  add(c, "purifying_salt_ghost", {attacker: mon("Gengar"), defender: mon("Garganacl", {ability: "Purifying Salt"}), move: {name: "Shadow Ball"}});
  add(c, "purifying_salt_other", {attacker: mon("Gengar"), defender: mon("Garganacl", {ability: "Purifying Salt"}), move: {name: "Sludge Bomb"}});
  add(c, "fur_coat_physical", {attacker: mon("Kingambit"), defender: mon("Furfrou", {ability: "Fur Coat"}), move: {name: "Iron Head"}});
  add(c, "fur_coat_special", {attacker: mon("Gengar"), defender: mon("Furfrou", {ability: "Fur Coat"}), move: {name: "Shadow Ball"}});
  add(c, "fur_coat_psyshock", {attacker: mon("Gardevoir"), defender: mon("Furfrou", {ability: "Fur Coat"}), move: {name: "Psyshock"}});
  add(c, "light_ball_pikachu", {attacker: mon("Pikachu", {item: "Light Ball"}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}});
  add(c, "light_ball_pikachu_physical", {attacker: mon("Pikachu", {item: "Light Ball"}), defender: mon("Pelipper"), move: {name: "Volt Tackle"}});
  add(c, "light_ball_raichu_no_boost", {attacker: mon("Raichu", {item: "Light Ball"}), defender: mon("Pelipper"), move: {name: "Thunderbolt"}});
  const intim = (target, extra = {}) => ({attacker: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), defender: mon(target, extra), move: {name: "Flare Blitz"}});
  add(c, "intimidate_on", intim("Meganium"));
  add(c, "intimidate_off", {attacker: mon("Incineroar", {ability: "Intimidate"}), defender: mon("Meganium"), move: {name: "Flare Blitz"}});
  add(c, "intimidate_defender_side_lowers_attacker", {attacker: mon("Meganium"), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Wood Hammer"}});
  for (const blocker of ["Clear Body", "White Smoke", "Hyper Cutter", "Full Metal Body", "Inner Focus", "Own Tempo", "Oblivious", "Scrappy"]) {
    add(c, `intimidate_vs_${blocker}`, {attacker: mon("Meganium", {ability: blocker}), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Wood Hammer"}});
  }
  add(c, "intimidate_vs_clear_amulet_absent", {attacker: mon("Meganium", {item: "Clear Amulet"}), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Wood Hammer"}});
  for (const reactor of ["Contrary", "Defiant", "Guard Dog", "Simple", "Competitive"]) {
    add(c, `intimidate_vs_${reactor}`, {attacker: mon("Meganium", {ability: reactor}), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Wood Hammer"}});
    add(c, `intimidate_vs_${reactor}_special`, {attacker: mon("Gardevoir", {ability: reactor}), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Psychic"}});
  }
  add(c, "intimidate_at_minus_six", {attacker: mon("Meganium", {boosts: {atk: -6}}), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Wood Hammer"}});
}

const BERRY_TARGETS = {"Occa Berry": "Scizor", "Passho Berry": "Torkoal", "Wacan Berry": "Pelipper", "Rindo Berry": "Swampert", "Yache Berry": "Garchomp", "Chople Berry": "Kingambit", "Kebia Berry": "Sylveon", "Shuca Berry": "Raichu", "Coba Berry": "Meganium", "Payapa Berry": "Toxicroak", "Tanga Berry": "Gardevoir", "Charti Berry": "Charizard", "Kasib Berry": "Gengar", "Haban Berry": "Dragonite", "Colbur Berry": "Gardevoir", "Babiri Berry": "Sylveon", "Roseli Berry": "Garchomp", "Chilan Berry": "Snorlax"};

// ---------------------------------------------------------------- final mods / defender
function defenseFinal() {
  const c = "defense_final";
  add(c, "multiscale_with_sr", {attacker: mon("Kingambit"), defender: mon("Dragonite", {ability: "Multiscale"}), move: {name: "Iron Head"}, field: {defenderSide: {isSR: true}}});
  add(c, "multiscale_with_spikes", {attacker: mon("Kingambit"), defender: mon("Dragonite", {ability: "Multiscale"}), move: {name: "Iron Head"}, field: {defenderSide: {spikes: 1}}});
  add(c, "multiscale_flying_ignores_spikes", {attacker: mon("Kingambit"), defender: mon("Dragonite", {ability: "Multiscale"}), move: {name: "Iron Head"}, field: {defenderSide: {spikes: 2}}});
  add(c, "multiscale_parental_bond", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Dragonite", {ability: "Multiscale"}), move: {name: "Body Slam"}});
  add(c, "fluffy_contact", {attacker: mon("Kingambit"), defender: mon("Machamp", {ability: "Fluffy"}), move: {name: "Iron Head"}});
  add(c, "fluffy_non_contact", {attacker: mon("Kingambit"), defender: mon("Machamp", {ability: "Fluffy"}), move: {name: "Stone Edge"}});
  add(c, "fluffy_fire", {attacker: mon("Charizard"), defender: mon("Machamp", {ability: "Fluffy"}), move: {name: "Flamethrower"}});
  add(c, "fluffy_fire_contact", {attacker: mon("Charizard"), defender: mon("Machamp", {ability: "Fluffy"}), move: {name: "Flare Blitz"}});
  add(c, "fluffy_long_reach", {attacker: mon("Kingambit", {ability: "Long Reach"}), defender: mon("Machamp", {ability: "Fluffy"}), move: {name: "Iron Head"}});
  add(c, "solid_rock_se", {attacker: mon("Swampert"), defender: mon("Camerupt", {ability: "Solid Rock"}), move: {name: "Surf"}});
  add(c, "filter_se", {attacker: mon("Lucario"), defender: mon("Aggron-Mega", {ability: "Filter"}), move: {name: "Close Combat"}});
  add(c, "filter_neutral", {attacker: mon("Kingambit"), defender: mon("Aggron-Mega", {ability: "Filter"}), move: {name: "Kowtow Cleave"}});
  add(c, "friend_guard", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}, field: {...DOUBLES, defenderSide: {isFriendGuard: true}}});
  add(c, "expert_belt_se", {attacker: mon("Kingambit", {item: "Expert Belt"}), defender: mon("Gardevoir"), move: {name: "Kowtow Cleave"}});
  add(c, "expert_belt_neutral", {attacker: mon("Kingambit", {item: "Expert Belt"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "life_orb", {attacker: mon("Kingambit", {item: "Life Orb"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "life_orb_spread", {attacker: mon("Garchomp", {item: "Life Orb"}), defender: mon("Kingambit"), move: {name: "Earthquake"}, field: DOUBLES});
  for (let n = 0; n <= 6; n++) {
    add(c, `metronome_${n}`, {attacker: mon("Kingambit", {item: "Metronome"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave", timesUsedWithMetronome: n}});
  }
  add(c, "muscle_band", {attacker: mon("Kingambit", {item: "Muscle Band"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "muscle_band_special", {attacker: mon("Gengar", {item: "Muscle Band"}), defender: mon("Incineroar"), move: {name: "Shadow Ball"}});
  add(c, "wise_glasses", {attacker: mon("Gengar", {item: "Wise Glasses"}), defender: mon("Incineroar"), move: {name: "Shadow Ball"}});
  for (const [item, move, user] of [["Black Glasses", "Kowtow Cleave", "Kingambit"], ["Charcoal", "Flamethrower", "Charizard"], ["Mystic Water", "Surf", "Swampert"], ["Fairy Feather", "Moonblast", "Gardevoir"],
    ["Dragon Fang", "Dragon Claw", "Garchomp"], ["Spell Tag", "Shadow Ball", "Gengar"], ["Silk Scarf", "Body Slam", "Snorlax"], ["Metal Coat", "Iron Head", "Kingambit"], ["Sharp Beak", "Brave Bird", "Talonflame"],
    ["Soft Sand", "Earthquake", "Garchomp"], ["Hard Stone", "Stone Edge", "Garchomp"], ["Never-Melt Ice", "Ice Beam", "Weavile"], ["Poison Barb", "Sludge Bomb", "Gengar"], ["Magnet", "Thunderbolt", "Raichu"],
    ["Miracle Seed", "Wood Hammer", "Meganium"], ["Twisted Spoon", "Psychic", "Gardevoir"], ["Black Belt", "Close Combat", "Lucario"], ["Silver Powder", "U-turn", "Scizor"]]) {
    add(c, `type_item_${item}`, {attacker: mon(user, {item}), defender: mon("Incineroar"), move: {name: move}});
  }
  add(c, "type_item_mismatch", {attacker: mon("Kingambit", {item: "Charcoal"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  for (const [berry, move, user] of [["Occa Berry", "Flamethrower", "Charizard"], ["Passho Berry", "Surf", "Swampert"], ["Wacan Berry", "Thunderbolt", "Raichu"], ["Rindo Berry", "Wood Hammer", "Meganium"],
    ["Yache Berry", "Ice Beam", "Weavile"], ["Chople Berry", "Close Combat", "Lucario"], ["Kebia Berry", "Sludge Bomb", "Gengar"], ["Shuca Berry", "Earthquake", "Garchomp"], ["Coba Berry", "Brave Bird", "Talonflame"],
    ["Payapa Berry", "Psychic", "Gardevoir"], ["Tanga Berry", "U-turn", "Scizor"], ["Charti Berry", "Stone Edge", "Garchomp"], ["Kasib Berry", "Shadow Ball", "Gengar"], ["Haban Berry", "Dragon Claw", "Garchomp"],
    ["Colbur Berry", "Kowtow Cleave", "Kingambit"], ["Babiri Berry", "Iron Head", "Kingambit"], ["Roseli Berry", "Moonblast", "Gardevoir"], ["Chilan Berry", "Body Slam", "Snorlax"]]) {
    add(c, `berry_${berry}_se`, {attacker: mon(user), defender: mon(BERRY_TARGETS[berry], {item: berry}), move: {name: move}});
  }
  add(c, "berry_neutral_no_effect", {attacker: mon("Kingambit"), defender: mon("Incineroar", {item: "Colbur Berry"}), move: {name: "Kowtow Cleave"}});
  add(c, "berry_chilan_normal_neutral", {attacker: mon("Snorlax"), defender: mon("Incineroar", {item: "Chilan Berry"}), move: {name: "Body Slam"}});
  add(c, "berry_ripen", {attacker: mon("Kingambit"), defender: mon("Gardevoir", {item: "Colbur Berry", ability: "Ripen"}), move: {name: "Kowtow Cleave"}});
  add(c, "berry_unnerve", {attacker: mon("Kingambit", {ability: "Unnerve"}), defender: mon("Gardevoir", {item: "Colbur Berry"}), move: {name: "Kowtow Cleave"}});
  add(c, "berry_second_hit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Gardevoir", {item: "Colbur Berry"}), move: {name: "Crunch"}});
  add(c, "iron_ball_ground_vs_flying", {attacker: mon("Garchomp"), defender: mon("Charizard", {item: "Iron Ball"}), move: {name: "Earthquake"}});
  add(c, "iron_ball_klutz_stays_immune", {attacker: mon("Garchomp"), defender: mon("Charizard", {item: "Iron Ball", ability: "Klutz"}), move: {name: "Earthquake"}});
  add(c, "stamina_second_hit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Mudsdale", {ability: "Stamina"}), move: {name: "Body Slam"}});
  add(c, "weak_armor_second_hit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Garchomp", {ability: "Weak Armor"}), move: {name: "Body Slam"}});
  add(c, "water_compaction_second_hit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Sandaconda", {ability: "Water Compaction"}), move: {name: "Aqua Tail"}});
  add(c, "mummy_swap_second_hit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Cofagrigus", {ability: "Mummy"}), move: {name: "Crunch"}});
}

// ---------------------------------------------------------------- immunities and mold breaker
function immunities() {
  const c = "immunities";
  const cases2 = [["Sap Sipper", "Wood Hammer", "Meganium", "Azumarill"], ["Flash Fire", "Flamethrower", "Charizard", "Chandelure"], ["Water Absorb", "Surf", "Swampert", "Vaporeon"],
    ["Dry Skin", "Surf", "Swampert", "Toxicroak"], ["Lightning Rod", "Thunderbolt", "Raichu", "Raichu"], ["Motor Drive", "Thunderbolt", "Raichu", "Luxray"], ["Volt Absorb", "Thunderbolt", "Raichu", "Jolteon"],
    ["Levitate", "Earthquake", "Garchomp", "Gengar"], ["Eelevate", "Earthquake", "Garchomp", "Raichu"], ["Bulletproof", "Shadow Ball", "Gengar", "Chesnaught"], ["Soundproof", "Hyper Voice", "Sylveon", "Forretress"],
    ["Queenly Majesty", "Sucker Punch", "Kingambit", "Tsareena"], ["Armor Tail", "Sucker Punch", "Kingambit", "Farigiraf"], ["Earth Eater", "Earthquake", "Garchomp", "Orthworm"]];
  for (const [ability, move, atk, def] of cases2) {
    add(c, `${ability}_immune`, {attacker: mon(atk), defender: mon(def, {ability}), move: {name: move}});
    add(c, `${ability}_mold_breaker`, {attacker: mon(atk, {ability: "Mold Breaker"}), defender: mon(def, {ability}), move: {name: move}});
  }
  add(c, "levitate_gravity", {attacker: mon("Garchomp"), defender: mon("Gengar", {ability: "Levitate"}), move: {name: "Earthquake"}, field: {isGravity: true}});
  add(c, "soundproof_clangorous_soul", {attacker: mon("Kommo-o"), defender: mon("Forretress", {ability: "Soundproof"}), move: {name: "Clanging Scales"}});
  add(c, "queenly_majesty_non_priority", {attacker: mon("Kingambit"), defender: mon("Tsareena", {ability: "Queenly Majesty"}), move: {name: "Kowtow Cleave"}});
  add(c, "mold_breaker_multiscale", {attacker: mon("Kingambit", {ability: "Mold Breaker"}), defender: mon("Dragonite", {ability: "Multiscale"}), move: {name: "Iron Head"}});
  add(c, "mold_breaker_fur_coat", {attacker: mon("Kingambit", {ability: "Mold Breaker"}), defender: mon("Furfrou", {ability: "Fur Coat"}), move: {name: "Iron Head"}});
  add(c, "mold_breaker_thick_fat", {attacker: mon("Charizard", {ability: "Mold Breaker"}), defender: mon("Snorlax", {ability: "Thick Fat"}), move: {name: "Flamethrower"}});
  add(c, "mold_breaker_unaware", {attacker: mon("Kingambit", {ability: "Mold Breaker", boosts: {atk: 2}}), defender: mon("Avalugg", {ability: "Unaware"}), move: {name: "Kowtow Cleave"}});
  add(c, "mold_breaker_filter", {attacker: mon("Lucario", {ability: "Mold Breaker"}), defender: mon("Aggron-Mega", {ability: "Filter"}), move: {name: "Close Combat"}});
  add(c, "mold_breaker_shell_armor_crit", {attacker: mon("Kingambit", {ability: "Mold Breaker"}), defender: mon("Incineroar", {ability: "Shell Armor"}), move: {name: "Kowtow Cleave", isCrit: true}});
  add(c, "mold_breaker_heavy_metal", {attacker: mon("Lucario", {ability: "Mold Breaker"}), defender: mon("Gardevoir", {ability: "Heavy Metal"}), move: {name: "Low Kick"}});
  add(c, "mold_breaker_non_ignorable_intimidate", {attacker: mon("Kingambit", {ability: "Mold Breaker"}), defender: mon("Incineroar", {ability: "Intimidate", abilityOn: true}), move: {name: "Kowtow Cleave"}});
  add(c, "mold_breaker_sand_veil_dead", {attacker: mon("Kingambit", {ability: "Mold Breaker"}), defender: mon("Garchomp", {ability: "Sand Veil"}), move: {name: "Kowtow Cleave"}});
  add(c, "ghost_immune_normal", {attacker: mon("Snorlax"), defender: mon("Gengar"), move: {name: "Body Slam"}});
  add(c, "freeze_dry_water", {attacker: mon("Weavile"), defender: mon("Swampert"), move: {name: "Freeze-Dry"}});
  add(c, "freeze_dry_water_dragon", {attacker: mon("Weavile"), defender: mon("Dragalge"), move: {name: "Freeze-Dry"}});
  add(c, "flying_press", {attacker: mon("Hawlucha"), defender: mon("Meganium"), move: {name: "Flying Press"}});
  add(c, "flying_press_vs_ghost", {attacker: mon("Hawlucha"), defender: mon("Gengar"), move: {name: "Flying Press"}});
  add(c, "flying_press_scrappy_ghost", {attacker: mon("Hawlucha", {ability: "Scrappy"}), defender: mon("Gengar"), move: {name: "Flying Press"}});
  add(c, "thousand_arrows_absent_skip", {attacker: mon("Garchomp"), defender: mon("Charizard"), move: {name: "Earthquake"}, field: {isGravity: true}});
}

// ---------------------------------------------------------------- protect
function protect() {
  const c = "protect";
  add(c, "protected", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}, field: {defenderSide: {isProtected: true}}});
  add(c, "feint_breaks", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Feint"}, field: {defenderSide: {isProtected: true}}});
  add(c, "unseen_fist_contact", {attacker: mon("Kingambit", {ability: "Unseen Fist"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}, field: {defenderSide: {isProtected: true}}});
  add(c, "unseen_fist_non_contact", {attacker: mon("Kingambit", {ability: "Unseen Fist"}), defender: mon("Incineroar"), move: {name: "Stone Edge"}, field: {defenderSide: {isProtected: true}}});
  add(c, "piercing_drill_contact", {attacker: mon("Excadrill", {ability: "Piercing Drill"}), defender: mon("Incineroar"), move: {name: "Iron Head"}, field: {defenderSide: {isProtected: true}}});
  add(c, "piercing_drill_no_protect", {attacker: mon("Excadrill", {ability: "Piercing Drill"}), defender: mon("Incineroar"), move: {name: "Iron Head"}});
  add(c, "unseen_fist_crit", {attacker: mon("Kingambit", {ability: "Unseen Fist"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave", isCrit: true}, field: {defenderSide: {isProtected: true}}});
  add(c, "unseen_fist_spread", {attacker: mon("Garchomp", {ability: "Unseen Fist"}), defender: mon("Kingambit"), move: {name: "Dragon Claw"}, field: {...DOUBLES, defenderSide: {isProtected: true}}});
}

// ---------------------------------------------------------------- speed-dependent moves
function speedMoves() {
  const c = "speed_moves";
  const pairs = [["Raichu", "Snorlax"], ["Raichu", "Garchomp"], ["Raichu", "Raichu"], ["Snorlax", "Raichu"], ["Garchomp", "Kingambit"], ["Metagross", "Weavile"]];
  for (const [a, d] of pairs) {
    add(c, `electro_ball_${a}_${d}`, {attacker: mon(a, {points: {spe: 32}}), defender: mon(d), move: {name: "Electro Ball"}});
    add(c, `gyro_ball_${a}_${d}`, {attacker: mon(a), defender: mon(d, {points: {spe: 32}}), move: {name: "Gyro Ball"}});
  }
  add(c, "electro_ball_defender_speed_zero_like", {attacker: mon("Raichu", {points: {spe: 32}}), defender: mon("Snorlax", {boosts: {spe: -6}, status: "par"}), move: {name: "Electro Ball"}});
  add(c, "gyro_ball_attacker_min_speed", {attacker: mon("Snorlax", {nature: "Brave", boosts: {spe: -6}, status: "par"}), defender: mon("Raichu", {boosts: {spe: 6}}), move: {name: "Gyro Ball"}});
  add(c, "tailwind_electro_ball", {attacker: mon("Raichu"), defender: mon("Garchomp"), move: {name: "Electro Ball"}, field: {attackerSide: {isTailwind: true}}});
  add(c, "choice_scarf_electro_ball", {attacker: mon("Raichu", {item: "Choice Scarf"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}});
  add(c, "iron_ball_gyro_ball", {attacker: mon("Metagross", {item: "Iron Ball"}), defender: mon("Raichu"), move: {name: "Gyro Ball"}});
  add(c, "swift_swim_rain", {attacker: mon("Basculegion", {ability: "Swift Swim"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}, field: {weather: "Rain"}});
  add(c, "chlorophyll_sun", {attacker: mon("Venusaur", {ability: "Chlorophyll"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}, field: {weather: "Sun"}});
  add(c, "sand_rush", {attacker: mon("Excadrill", {ability: "Sand Rush"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}, field: {weather: "Sand"}});
  add(c, "slush_rush", {attacker: mon("Beartic", {ability: "Slush Rush"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}, field: {weather: "Snow"}});
  add(c, "surge_surfer", {attacker: mon("Raichu-Alola", {ability: "Surge Surfer"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}, field: {terrain: "Electric"}});
  add(c, "unburden_on", {attacker: mon("Hawlucha", {ability: "Unburden", abilityOn: true}), defender: mon("Garchomp"), move: {name: "Electro Ball"}});
  add(c, "slow_start_on", {attacker: mon("Snorlax", {ability: "Slow Start", abilityOn: true}), defender: mon("Garchomp"), move: {name: "Electro Ball"}});
  add(c, "quick_feet_status", {attacker: mon("Snorlax", {ability: "Quick Feet", status: "brn"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}});
  add(c, "paralysis_halves", {attacker: mon("Raichu", {status: "par"}), defender: mon("Garchomp"), move: {name: "Electro Ball"}});
  add(c, "speed_boost_plus_two", {attacker: mon("Raichu", {boosts: {spe: 2}}), defender: mon("Garchomp", {boosts: {spe: -2}}), move: {name: "Electro Ball"}});
  add(c, "analytic_turn_order_with_scarf", {attacker: mon("Metagross", {ability: "Analytic", item: "Choice Scarf"}), defender: mon("Raichu"), move: {name: "Psychic"}});
  add(c, "payback_tailwind_defender", {attacker: mon("Raichu"), defender: mon("Metagross"), move: {name: "Payback"}, field: {defenderSide: {isTailwind: true}}});
}

// ---------------------------------------------------------------- multi-hit and repeated use
function multihit() {
  const c = "multihit";
  add(c, "bone_rush_default", {attacker: mon("Garchomp"), defender: mon("Kingambit"), move: {name: "Bone Rush"}});
  for (const h of [2, 3, 4, 5]) add(c, `bone_rush_${h}`, {attacker: mon("Garchomp"), defender: mon("Kingambit"), move: {name: "Bone Rush", hits: h}});
  add(c, "skill_link_rock_blast", {attacker: mon("Heracross-Mega", {ability: "Skill Link"}), defender: mon("Charizard"), move: {name: "Rock Blast"}});
  add(c, "icicle_spear_skill_link", {attacker: mon("Heracross-Mega", {ability: "Skill Link"}), defender: mon("Garchomp"), move: {name: "Pin Missile"}});
  add(c, "population_bomb", {attacker: mon("Maushold"), defender: mon("Incineroar"), move: {name: "Population Bomb"}});
  add(c, "population_bomb_hits_7", {attacker: mon("Maushold"), defender: mon("Incineroar"), move: {name: "Population Bomb", hits: 7}});
  add(c, "triple_axel", {attacker: mon("Weavile"), defender: mon("Garchomp"), move: {name: "Triple Axel"}});
  add(c, "triple_axel_hits_2", {attacker: mon("Weavile"), defender: mon("Garchomp"), move: {name: "Triple Axel", hits: 2}});
  add(c, "dual_wingbeat", {attacker: mon("Talonflame"), defender: mon("Meganium"), move: {name: "Dual Wingbeat"}});
  add(c, "dragon_darts", {attacker: mon("Dragapult"), defender: mon("Incineroar"), move: {name: "Dragon Darts"}});
  add(c, "parental_bond", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Incineroar"), move: {name: "Body Slam"}});
  add(c, "parental_bond_spread_single_hit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Incineroar"), move: {name: "Earthquake"}, field: DOUBLES});
  add(c, "parental_bond_fixed_damage", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Incineroar"), move: {name: "Seismic Toss"}});
  add(c, "parental_bond_multihit_move", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Incineroar"), move: {name: "Double Hit"}});
  add(c, "parental_bond_gyro_ball_gooey", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Goodra", {ability: "Gooey"}), move: {name: "Gyro Ball"}});
  add(c, "parental_bond_life_orb_crit", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond", item: "Life Orb"}), defender: mon("Incineroar"), move: {name: "Body Slam", isCrit: true}});
  for (const n of [2, 3]) {
    add(c, `overheat_times_${n}`, {attacker: mon("Charizard", {points: P.spec}), defender: mon("Meganium"), move: {name: "Overheat", timesUsed: n}});
    add(c, `draco_meteor_times_${n}`, {attacker: mon("Garchomp"), defender: mon("Dragonite"), move: {name: "Draco Meteor", timesUsed: n}});
    add(c, `make_it_rain_times_${n}`, {attacker: mon("Gholdengo"), defender: mon("Incineroar"), move: {name: "Make It Rain", timesUsed: n}});
    add(c, `close_combat_times_${n}`, {attacker: mon("Lucario"), defender: mon("Kingambit"), move: {name: "Close Combat", timesUsed: n}});
    add(c, `overheat_contrary_times_${n}`, {attacker: mon("Charizard", {ability: "Contrary"}), defender: mon("Meganium"), move: {name: "Overheat", timesUsed: n}});
    add(c, `overheat_white_herb_times_${n}`, {attacker: mon("Charizard", {item: "White Herb"}), defender: mon("Meganium"), move: {name: "Overheat", timesUsed: n}});
    add(c, `overheat_simple_times_${n}`, {attacker: mon("Charizard", {ability: "Simple"}), defender: mon("Meganium"), move: {name: "Overheat", timesUsed: n}});
    add(c, `flamethrower_times_${n}`, {attacker: mon("Charizard"), defender: mon("Meganium"), move: {name: "Flamethrower", timesUsed: n}});
    add(c, `stamina_times_${n}`, {attacker: mon("Kingambit"), defender: mon("Mudsdale", {ability: "Stamina"}), move: {name: "Iron Head", timesUsed: n}});
    add(c, `weak_armor_times_${n}`, {attacker: mon("Kingambit"), defender: mon("Garchomp", {ability: "Weak Armor"}), move: {name: "Iron Head", timesUsed: n}});
    add(c, `weak_armor_white_herb_times_${n}`, {attacker: mon("Kingambit"), defender: mon("Garchomp", {ability: "Weak Armor", item: "White Herb"}), move: {name: "Iron Head", timesUsed: n}});
    add(c, `water_compaction_times_${n}`, {attacker: mon("Swampert"), defender: mon("Sandaconda", {ability: "Water Compaction"}), move: {name: "Surf", timesUsed: n}});
    add(c, `mummy_times_${n}`, {attacker: mon("Kingambit", {ability: "Supreme Overlord", alliesFainted: 2}), defender: mon("Cofagrigus", {ability: "Mummy"}), move: {name: "Kowtow Cleave", timesUsed: n}});
    add(c, `sand_spit_times_${n}`, {attacker: mon("Charizard"), defender: mon("Sandaconda", {ability: "Sand Spit"}), move: {name: "Flamethrower", timesUsed: n}});
    add(c, `seed_sower_times_${n}`, {attacker: mon("Garchomp"), defender: mon("Meganium", {ability: "Seed Sower"}), move: {name: "Earthquake", timesUsed: n}});
  }
  add(c, "bone_rush_times_2", {attacker: mon("Garchomp"), defender: mon("Kingambit"), move: {name: "Bone Rush", timesUsed: 2}});
}

// ---------------------------------------------------------------- fixed damage
function fixed() {
  const c = "fixed";
  add(c, "seismic_toss", {attacker: mon("Audino"), defender: mon("Kingambit"), move: {name: "Seismic Toss"}});
  add(c, "seismic_toss_vs_ghost", {attacker: mon("Audino"), defender: mon("Gengar"), move: {name: "Seismic Toss"}});
  add(c, "night_shade", {attacker: mon("Gengar"), defender: mon("Kingambit"), move: {name: "Night Shade"}});
  add(c, "night_shade_vs_normal", {attacker: mon("Gengar"), defender: mon("Snorlax"), move: {name: "Night Shade"}});
  add(c, "seismic_toss_life_orb_ignored", {attacker: mon("Audino", {item: "Life Orb"}), defender: mon("Kingambit"), move: {name: "Seismic Toss"}});
  add(c, "counter_zero", {attacker: mon("Lucario"), defender: mon("Kingambit"), move: {name: "Counter"}});
  add(c, "super_fang_zero", {attacker: mon("Raichu"), defender: mon("Kingambit"), move: {name: "Super Fang"}});
}

// ---------------------------------------------------------------- type specials
function typeSpecial() {
  const c = "type_special";
  add(c, "aura_wheel_morpeko", {attacker: mon("Morpeko"), defender: mon("Pelipper"), move: {name: "Aura Wheel"}});
  add(c, "aura_wheel_hangry", {attacker: mon("Morpeko-Hangry"), defender: mon("Gardevoir"), move: {name: "Aura Wheel"}});
  add(c, "struggle", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Struggle"}});
  add(c, "struggle_vs_ghost", {attacker: mon("Kingambit"), defender: mon("Gengar"), move: {name: "Struggle"}});
  add(c, "weather_ball_technician_sand", {attacker: mon("Scizor", {ability: "Technician"}), defender: mon("Charizard"), move: {name: "Weather Ball"}, field: {weather: "Sand"}});
  add(c, "terrain_pulse_flying_ungrounded", {attacker: mon("Charizard"), defender: mon("Vileplume"), move: {name: "Terrain Pulse"}, field: {terrain: "Psychic"}});
  add(c, "terrain_pulse_vs_dark_psychic_terrain", {attacker: mon("Gardevoir"), defender: mon("Kingambit"), move: {name: "Terrain Pulse"}, field: {terrain: "Psychic"}});
  add(c, "clangorous_soul_soundproof", {attacker: mon("Kommo-o"), defender: mon("Forretress", {ability: "Soundproof"}), move: {name: "Clangorous Soul"}});
  add(c, "future_sight", {attacker: mon("Gardevoir"), defender: mon("Kingambit"), move: {name: "Future Sight"}});
}

// ---------------------------------------------------------------- KO chance, residuals, hazards
function ko() {
  const c = "ko";
  const base = {attacker: mon("Kingambit", {nature: "Adamant", points: P.phys}), move: {name: "Kowtow Cleave"}};
  add(c, "guaranteed_ohko", {...base, defender: mon("Gardevoir")});
  add(c, "chance_ohko", {attacker: mon("Kingambit", {nature: "Adamant", points: P.phys, item: "Life Orb"}), defender: mon("Gardevoir", {points: {hp: 32, def: 32}}), move: {name: "Kowtow Cleave"}});
  add(c, "guaranteed_2hko", {...base, defender: mon("Incineroar")});
  add(c, "chance_2hko", {...base, defender: mon("Incineroar", {nature: "Impish", points: P.bulk})});
  add(c, "3hko", {attacker: mon("Kingambit"), defender: mon("Incineroar", {nature: "Impish", points: P.bulk}), move: {name: "Iron Head"}});
  add(c, "4hko", {attacker: mon("Kingambit"), defender: mon("Avalugg", {points: P.bulk}), move: {name: "Iron Head"}});
  add(c, "5_to_9hko", {attacker: mon("Kingambit"), defender: mon("Avalugg", {nature: "Impish", points: P.bulk}), move: {name: "Sucker Punch"}});
  add(c, "possible_nhko", {attacker: mon("Pikachu"), defender: mon("Avalugg", {nature: "Impish", points: P.bulk}), move: {name: "Quick Attack"}});
  add(c, "not_a_ko", {attacker: mon("Pikachu", {boosts: {atk: -6}}), defender: mon("Avalugg", {nature: "Impish", points: P.bulk}), move: {name: "Quick Attack"}});
  add(c, "leftovers", {...base, defender: mon("Incineroar", {item: "Leftovers"})});
  add(c, "leftovers_2hko", {...base, defender: mon("Incineroar", {nature: "Impish", points: P.bulk, item: "Leftovers"})});
  add(c, "leftovers_knocked_off", {attacker: mon("Kingambit", {points: P.phys}), defender: mon("Incineroar", {item: "Leftovers"}), move: {name: "Knock Off"}});
  add(c, "leftovers_sticky_hold_knock_off", {attacker: mon("Kingambit", {points: P.phys}), defender: mon("Incineroar", {item: "Leftovers", ability: "Sticky Hold"}), move: {name: "Knock Off"}});
  add(c, "sitrus_no_residual", {...base, defender: mon("Incineroar", {item: "Sitrus Berry"})});
  add(c, "sand_chip", {...base, defender: mon("Incineroar"), field: {weather: "Sand"}});
  add(c, "sand_immune_rock", {...base, defender: mon("Tyranitar"), field: {weather: "Sand"}});
  add(c, "sand_overcoat", {...base, defender: mon("Incineroar", {ability: "Overcoat"}), field: {weather: "Sand"}});
  add(c, "sand_magic_guard", {...base, defender: mon("Incineroar", {ability: "Magic Guard"}), field: {weather: "Sand"}});
  add(c, "hail_absent_snow_no_chip", {...base, defender: mon("Incineroar"), field: {weather: "Snow"}});
  add(c, "ice_body_snow", {...base, defender: mon("Incineroar", {ability: "Ice Body"}), field: {weather: "Snow"}});
  add(c, "rain_dish", {...base, defender: mon("Incineroar", {ability: "Rain Dish"}), field: {weather: "Rain"}});
  add(c, "dry_skin_rain", {...base, defender: mon("Incineroar", {ability: "Dry Skin"}), field: {weather: "Rain"}});
  add(c, "dry_skin_sun", {...base, defender: mon("Incineroar", {ability: "Dry Skin"}), field: {weather: "Sun"}});
  add(c, "solar_power_sun_chip", {...base, defender: mon("Incineroar", {ability: "Solar Power"}), field: {weather: "Sun"}});
  add(c, "grassy_terrain_recovery", {...base, defender: mon("Incineroar"), field: {terrain: "Grassy"}});
  add(c, "grassy_terrain_flying_no_recovery", {...base, defender: mon("Charizard"), field: {terrain: "Grassy"}});
  add(c, "leech_seed_defender", {...base, defender: mon("Incineroar"), field: {defenderSide: {isSeeded: true}}});
  add(c, "leech_seed_attacker", {...base, defender: mon("Incineroar"), field: {attackerSide: {isSeeded: true}}});
  add(c, "leech_seed_attacker_big_root_defender", {...base, defender: mon("Incineroar", {item: "Big Root"}), field: {attackerSide: {isSeeded: true}}});
  add(c, "leech_seed_liquid_ooze", {attacker: mon("Kingambit", {ability: "Liquid Ooze", points: P.phys}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}, field: {attackerSide: {isSeeded: true}}});
  add(c, "leech_seed_magic_guard", {...base, defender: mon("Incineroar", {ability: "Magic Guard"}), field: {defenderSide: {isSeeded: true}}});
  add(c, "nightmare", {...base, defender: mon("Incineroar", {status: "slp"}), field: {defenderSide: {isNightmared: true}}});
  add(c, "bad_dreams", {attacker: mon("Spiritomb", {ability: "Bad Dreams"}), defender: mon("Incineroar", {status: "slp"}), move: {name: "Dark Pulse"}});
  add(c, "salt_cure_water", {...base, defender: mon("Swampert"), field: {defenderSide: {isSaltCured: true}}});
  add(c, "salt_cure_other", {...base, defender: mon("Incineroar"), field: {defenderSide: {isSaltCured: true}}});
  add(c, "poison", {...base, defender: mon("Incineroar", {status: "psn"})});
  add(c, "poison_heal", {...base, defender: mon("Incineroar", {status: "psn", ability: "Poison Heal"})});
  for (const t of [1, 2, 3, 4]) add(c, `toxic_counter_${t}`, {...base, defender: mon("Incineroar", {status: "tox", toxicCounter: t})});
  add(c, "toxic_poison_heal", {...base, defender: mon("Incineroar", {status: "tox", toxicCounter: 2, ability: "Poison Heal"})});
  add(c, "burn", {...base, defender: mon("Incineroar", {status: "brn"})});
  add(c, "burn_heatproof", {...base, defender: mon("Incineroar", {status: "brn", ability: "Heatproof"})});
  add(c, "burn_magic_guard", {...base, defender: mon("Incineroar", {status: "brn", ability: "Magic Guard"})});
  add(c, "stealth_rock_neutral", {...base, defender: mon("Incineroar"), field: {defenderSide: {isSR: true}}});
  add(c, "stealth_rock_4x", {...base, defender: mon("Charizard"), field: {defenderSide: {isSR: true}}});
  add(c, "stealth_rock_quarter", {...base, defender: mon("Lucario"), field: {defenderSide: {isSR: true}}});
  add(c, "stealth_rock_magic_guard", {...base, defender: mon("Charizard", {ability: "Magic Guard"}), field: {defenderSide: {isSR: true}}});
  for (const n of [1, 2, 3]) add(c, `spikes_${n}`, {...base, defender: mon("Incineroar"), field: {defenderSide: {spikes: n}}});
  add(c, "spikes_flying", {...base, defender: mon("Charizard"), field: {defenderSide: {spikes: 3}}});
  add(c, "spikes_levitate", {...base, defender: mon("Gengar", {ability: "Levitate"}), field: {defenderSide: {spikes: 3}}});
  add(c, "spikes_eelevate", {...base, defender: mon("Incineroar", {ability: "Eelevate"}), field: {defenderSide: {spikes: 3}}});
  add(c, "spikes_and_rocks_and_leftovers", {...base, defender: mon("Incineroar", {item: "Leftovers"}), field: {defenderSide: {spikes: 2, isSR: true}}});
  add(c, "trapping_move", {attacker: mon("Charizard"), defender: mon("Incineroar"), move: {name: "Fire Spin"}});
  add(c, "trapping_whirlpool", {attacker: mon("Swampert"), defender: mon("Charizard"), move: {name: "Whirlpool"}});
  add(c, "psychic_noise_heal_block", {attacker: mon("Gardevoir"), defender: mon("Incineroar", {item: "Leftovers"}), move: {name: "Psychic Noise"}});
  add(c, "psychic_noise_sheer_force", {attacker: mon("Gardevoir", {ability: "Sheer Force"}), defender: mon("Incineroar", {item: "Leftovers"}), move: {name: "Psychic Noise"}});
  add(c, "cur_hp_partial", {...base, defender: mon("Incineroar", {curHP: 90})});
  add(c, "cur_hp_partial_with_leftovers", {...base, defender: mon("Incineroar", {curHP: 90, item: "Leftovers"})});
  add(c, "multihit_ko_bone_rush", {attacker: mon("Garchomp", {points: P.phys}), defender: mon("Kingambit"), move: {name: "Bone Rush", hits: 5}});
  add(c, "multihit_ko_approx", {attacker: mon("Maushold", {points: P.phys}), defender: mon("Incineroar"), move: {name: "Population Bomb"}});
  add(c, "times_used_ko", {attacker: mon("Charizard", {points: P.spec}), defender: mon("Meganium"), move: {name: "Overheat", timesUsed: 2}});
  add(c, "parental_bond_ko", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond", points: P.phys}), defender: mon("Gardevoir"), move: {name: "Body Slam"}});
  add(c, "fixed_damage_ko", {attacker: mon("Audino"), defender: mon("Pikachu"), move: {name: "Seismic Toss"}});
  add(c, "immune_no_ko", {attacker: mon("Garchomp"), defender: mon("Charizard"), move: {name: "Earthquake"}});
}

// ---------------------------------------------------------------- recoil and recovery text
function recoilRecovery() {
  const c = "recoil_recovery";
  add(c, "double_edge", {attacker: mon("Snorlax"), defender: mon("Incineroar"), move: {name: "Double-Edge"}});
  add(c, "wild_charge", {attacker: mon("Raichu"), defender: mon("Pelipper"), move: {name: "Wild Charge"}});
  add(c, "head_smash_overflow", {attacker: mon("Tyrantrum", {points: P.phys}), defender: mon("Pikachu"), move: {name: "Head Smash"}});
  add(c, "flare_blitz_rock_head", {attacker: mon("Incineroar", {ability: "Rock Head"}), defender: mon("Meganium"), move: {name: "Flare Blitz"}});
  add(c, "high_jump_kick", {attacker: mon("Lucario"), defender: mon("Incineroar"), move: {name: "High Jump Kick"}});
  add(c, "high_jump_kick_overflow", {attacker: mon("Lucario", {points: P.phys}), defender: mon("Pikachu"), move: {name: "High Jump Kick"}});
  add(c, "steel_beam", {attacker: mon("Archaludon"), defender: mon("Gardevoir"), move: {name: "Steel Beam"}});
  add(c, "struggle_recoil", {attacker: mon("Kingambit"), defender: mon("Incineroar"), move: {name: "Struggle"}});
  add(c, "drain_punch", {attacker: mon("Lucario"), defender: mon("Incineroar"), move: {name: "Drain Punch"}});
  add(c, "drain_punch_big_root", {attacker: mon("Lucario", {item: "Big Root"}), defender: mon("Incineroar"), move: {name: "Drain Punch"}});
  add(c, "giga_drain_overflow", {attacker: mon("Meganium", {points: P.spec}), defender: mon("Pikachu", {curHP: 10}), move: {name: "Giga Drain"}});
  add(c, "draining_kiss", {attacker: mon("Gardevoir"), defender: mon("Incineroar"), move: {name: "Draining Kiss"}});
  add(c, "parental_bond_drain", {attacker: mon("Kangaskhan-Mega", {ability: "Parental Bond"}), defender: mon("Incineroar"), move: {name: "Drain Punch"}});
  add(c, "shell_bell", {attacker: mon("Kingambit", {item: "Shell Bell"}), defender: mon("Incineroar"), move: {name: "Kowtow Cleave"}});
  add(c, "shell_bell_multihit", {attacker: mon("Garchomp", {item: "Shell Bell"}), defender: mon("Kingambit"), move: {name: "Bone Rush", hits: 3}});
  add(c, "pain_split_recovery", {attacker: mon("Gengar", {curHP: 30}), defender: mon("Incineroar"), move: {name: "Pain Split"}});
  add(c, "leech_life", {attacker: mon("Scizor"), defender: mon("Gardevoir"), move: {name: "Leech Life"}});
  add(c, "damage_over_two_turns_recoil", {attacker: mon("Snorlax"), defender: mon("Incineroar"), move: {name: "Double-Edge", timesUsed: 2}});
}

// ---------------------------------------------------------------- seeded random sweep
function mulberry32(seed) {
  return function () {
    seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randomSweep() {
  const c = "random";
  const rnd = mulberry32(20260902);
  const pick = (arr) => arr[Math.floor(rnd() * arr.length)];
  const chance = (p) => rnd() < p;
  const SPECIES = ["Kingambit", "Incineroar", "Garchomp", "Charizard", "Charizard-Mega-Y", "Charizard-Mega-X", "Metagross", "Metagross-Mega", "Raichu", "Gardevoir", "Gardevoir-Mega",
    "Swampert", "Pelipper", "Altaria", "Altaria-Mega", "Archaludon", "Basculegion", "Basculegion-F", "Rotom-Wash", "Rotom-Heat", "Dragonite", "Tyranitar", "Excadrill", "Gengar",
    "Gengar-Mega", "Lucario", "Lucario-Mega", "Vileplume", "Meganium", "Torkoal", "Whimsicott", "Meowstic", "Meowstic-F", "Farigiraf", "Avalugg", "Sneasler", "Annihilape",
    "Kommo-o", "Hatterene", "Grimmsnarl", "Toxapex", "Audino", "Spiritomb", "Mimikyu", "Pikachu", "Morpeko", "Talonflame", "Sylveon", "Mawile", "Mawile-Mega", "Kangaskhan-Mega",
    "Aggron-Mega", "Scizor-Mega", "Politoed", "Arcanine", "Volcarona", "Hydreigon", "Dragonite-Mega", "Gyarados", "Gyarados-Mega", "Weavile", "Clefable", "Chandelure", "Snorlax",
    "Azumarill", "Glimmora", "Primarina", "Milotic", "Heracross-Mega", "Maushold", "Dragapult", "Gholdengo"];
  const MOVES = ["Kowtow Cleave", "Iron Head", "Sucker Punch", "Flare Blitz", "Knock Off", "Fake Out", "Earthquake", "Dragon Claw", "Rock Slide", "Stone Edge", "Heat Wave",
    "Flamethrower", "Air Slash", "Psychic", "Moonblast", "Dazzling Gleam", "Shadow Ball", "Sludge Bomb", "Thunderbolt", "Volt Tackle", "Surf", "Liquidation", "Ice Beam",
    "Icy Wind", "Wood Hammer", "Grassy Glide", "Close Combat", "Body Press", "Foul Play", "Psyshock", "Hyper Voice", "Body Slam", "Brave Bird", "U-turn", "Bullet Punch",
    "Draco Meteor", "Overheat", "Make It Rain", "Play Rough", "Crunch", "Low Kick", "Grass Knot", "Heavy Slam", "Heat Crash", "Eruption", "Weather Ball", "Terrain Pulse",
    "Expanding Force", "Rising Voltage", "Electro Ball", "Gyro Ball", "Bone Rush", "Population Bomb", "Pin Missile", "Freeze-Dry", "Hex", "Facade", "Drain Punch", "Giga Drain",
    "Double-Edge", "Head Smash", "High Jump Kick", "Seismic Toss", "Night Shade", "Final Gambit", "Hard Press", "Flail", "Stored Power", "Poltergeist", "Acrobatics", "Struggle"];
  const ABILITIES = [null, null, null, "Intimidate", "Supreme Overlord", "Technician", "Sheer Force", "Tough Claws", "Huge Power", "Guts", "Thick Fat", "Fur Coat", "Multiscale",
    "Solid Rock", "Filter", "Levitate", "Flash Fire", "Water Absorb", "Lightning Rod", "Sap Sipper", "Unaware", "Mold Breaker", "Adaptability", "Pixilate", "Aerilate", "Refrigerate",
    "Sharpness", "Strong Jaw", "Iron Fist", "Reckless", "Analytic", "Sand Force", "Solar Power", "Blaze", "Torrent", "Swift Swim", "Chlorophyll", "Heavy Metal", "Light Metal",
    "Scrappy", "Sniper", "Merciless", "Parental Bond", "Fluffy", "Purifying Salt", "Water Bubble", "Heatproof", "Marvel Scale", "Stamina", "Weak Armor", "Contrary", "Simple",
    "Defiant", "Competitive", "Clear Body", "Inner Focus", "Magic Guard", "Poison Heal", "Ice Body", "Rain Dish", "Dry Skin", "Mega Sol", "Dragonize", "Eelevate", "Fire Mane", "Piercing Drill", "Unseen Fist"];
  const ITEMS = [null, null, null, "Life Orb", "Expert Belt", "Leftovers", "Sitrus Berry", "Muscle Band", "Wise Glasses", "Metronome", "Choice Scarf", "Iron Ball", "Black Glasses",
    "Charcoal", "Mystic Water", "Fairy Feather", "Colbur Berry", "Occa Berry", "Passho Berry", "Wacan Berry", "Chople Berry", "Shell Bell", "Big Root", "White Herb", "Light Ball", "Charizardite Y", "Kingambit"];
  const NATURES = ["Adamant", "Jolly", "Modest", "Timid", "Impish", "Careful", "Bold", "Calm", "Brave", "Quiet", "Hardy", "Sassy", "Relaxed"];
  const STATUSES = ["", "", "", "", "brn", "psn", "tox", "par", "slp", "frz"];
  const WEATHERS = [null, null, null, "Sun", "Rain", "Sand", "Snow"];
  const TERRAINS = [null, null, null, "Electric", "Grassy", "Psychic", "Misty"];
  const spread = () => {
    const keys = ["hp", "atk", "def", "spa", "spd", "spe"];
    const r = rnd();
    if (r < 0.3) return {};
    if (r < 0.7) return {[pick(keys)]: 32, [pick(keys)]: 32, [pick(keys)]: 2};
    const pts = {};
    let left = 66;
    for (const k of keys) {
      const v = Math.min(32, Math.floor(rnd() * 33), left);
      if (v > 0) pts[k] = v;
      left -= v;
    }
    return pts;
  };
  const boosts = () => {
    const b = {};
    for (const k of ["atk", "def", "spa", "spd", "spe"]) if (chance(0.15)) b[k] = Math.floor(rnd() * 9) - 4;
    return b;
  };
  const sideConditions = () => ({isReflect: chance(0.1), isLightScreen: chance(0.1), isAuroraVeil: chance(0.05), isTailwind: chance(0.1), isHelpingHand: chance(0.1), isFriendGuard: chance(0.05),
    isSR: chance(0.1), spikes: chance(0.1) ? Math.floor(rnd() * 4) : 0, isSeeded: chance(0.05), isProtected: chance(0.03), isCharge: chance(0.03)});
  const item = () => { const i = pick(ITEMS); return i === "Kingambit" ? "Metronome" : i; };
  for (let i = 0; i < 220; i++) {
    const attacker = mon(pick(SPECIES), {ability: pick(ABILITIES), abilityOn: chance(0.5), item: item(), nature: pick(NATURES), points: spread(), boosts: boosts(),
      status: pick(STATUSES), alliesFainted: chance(0.2) ? Math.floor(rnd() * 6) : 0, curHP: null});
    const defender = mon(pick(SPECIES), {ability: pick(ABILITIES), abilityOn: chance(0.5), item: item(), nature: pick(NATURES), points: spread(), boosts: boosts(),
      status: pick(STATUSES), toxicCounter: chance(0.2) ? 1 + Math.floor(rnd() * 4) : 0});
    if (chance(0.3)) attacker.curHP = 1 + Math.floor(rnd() * 150);
    if (chance(0.3)) defender.curHP = 1 + Math.floor(rnd() * 150);
    const move = {name: pick(MOVES), isCrit: chance(0.1), timesUsed: chance(0.1) ? 2 : 1, timesUsedWithMetronome: chance(0.2) ? 1 + Math.floor(rnd() * 5) : 1};
    const field = {gameType: chance(0.6) ? "Doubles" : "Singles", weather: pick(WEATHERS), terrain: pick(TERRAINS), isGravity: chance(0.05), isMagicRoom: chance(0.03), isWonderRoom: chance(0.03),
      attackerSide: sideConditions(), defenderSide: sideConditions()};
    add(c, "case", {attacker, defender, move, field});
  }
}

export function scenarios() {
  cases.length = 0;
  counters.clear();
  baseline(); weather(); terrain(); screens(); crit(); status(); hpScaling(); weight(); statOverrides(); knockOff(); abilityBp(); ate(); attackDefense();
  defenseFinal(); immunities(); protect(); speedMoves(); multihit(); fixed(); typeSpecial(); ko(); recoilRecovery(); randomSweep();
  return cases;
}
