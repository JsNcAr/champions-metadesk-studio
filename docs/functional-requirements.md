# Functional Requirements

## Box Management

### FR-1 Add a Pokemon to the box
- The user must be able to add a new Pokemon by providing only the Pokemon name.
- The system must look up the Pokemon through PokéAPI and store the resulting data in the box.
- The system should avoid creating duplicate box entries for the same Pokemon identity.

### FR-2 View box entries on the default team viewer page
- The user must be able to see all Pokemon added to the box.
- Each entry should show at least the Pokemon image, display name, and types.
- The default view should be optimized for scanning the current box.

### FR-3 Inspect detailed Pokemon information
- The user must be able to select a Pokemon from the box.
- The detail view must show stats, typing, abilities, and additional information.
- The detail view should also include moveset data and possible abilities when available.

### FR-4 Sort box entries
- The user must be able to sort Pokemon in the box by stat values.
- Sorting should support at least ascending and descending order.
- The user should be able to sort by one stat at a time, with room for multi-key sorting later.

### FR-5 Filter box entries
- The user must be able to filter the box using criteria such as stat ranges and form availability.
- Filtering should support multiple criteria at once.
- The user should be able to clear filters and return to the full box list.

### FR-6 Advanced box visualization
- The user must be able to choose extra stats to display in the box view.
- The system should support default stats plus selected additional stats such as HP and Speed.
- The system should also support an all-stats view.

### FR-7 Export to CSV
- The user must be able to export box stats to CSV.
- The exported file should be useful for external analysis in spreadsheets or other tools.
- Export should preserve the currently visible or selected dataset when appropriate.

### FR-8 Show damage taken by attack type
- The user must be able to see the damage taken by each attack type.
- The system should group attack types by multiplier categories such as 4x, 2x, 1x, 0.5x, and 0x.
- The presentation should be usable for quickly spotting weaknesses and resistances.

## Team Building

### FR-9 Add a Pokemon from the box to a team
- The user must be able to select a Pokemon from the box and add it to a team.
- The system should prevent invalid team assignments.
- The same Pokemon may appear in multiple teams if the product rules allow it, or the product should define a restriction clearly.

### FR-10 Manage multiple teams
- The user must be able to create, view, rename, update, and delete teams.
- The user must be able to switch between teams quickly.
- Team data must be stored independently so changes do not leak across teams.

### FR-11 Edit team items and movesets
- The user must be able to set the held item for each Pokemon on a team.
- The user must be able to set or edit movesets for each Pokemon on a team.
- The system should validate moves and items against known game data where possible.

### FR-11a Edit Champions stat-point spreads
- The user must be able to set a nature and stat points per Pokemon following Pokémon Champions rules: 0–32 points per stat, 66 points per Pokemon, level fixed at 50, IVs fixed at 31.
- The system must compute battle stats with the Champions formula (HP = base + points + 75; other stats = floor(nature × (base + points + 20))).
- The system must refuse spreads over the budget and report unspread slots and unused points in the team health checks.
- Showdown pastes must be accepted in both conventions: point values on the `EVs:` line (Champions format) and mainline EV spreads, which are converted without changing any stat and flagged in the preview.

### FR-12 Show offensive type coverage
- The user must be able to see the type coverage of damaging moves on a team.
- The system should summarize which opposing types the team hits for super effective, neutral, not very effective, or no damage.
- The summary should reflect the Pokemon moves currently assigned to the team.

### FR-13 Show team stat totals
- The user must be able to see a combined stat summary for the whole team.
- The system should sum stats across all Pokemon on the team.
- The summary should support quick comparison between teams.

### FR-14 Find tournament teams buildable from the box
- The user must be able to filter tournament teams by how many members are missing from the box (none, at most one, two or three).
- Each listed team must show how many of its members are in the box and mark the missing ones.
- Only owned box entries count; planned entries do not. A Mega form counts as its base species; other forms are distinct.
- The filter must keep exact counts and paging (it is applied in the query, not after).

### FR-15 Damage calculator
- The user must be able to compute the damage of every move of one Pokémon against another, in both directions at once, with the sixteen rolls, a description and the KO chance.
- The calculation must follow Pokémon Champions rules (stat points, level 50) and account for weather, terrain, screens, Tailwind, Helping Hand, hazards, Leech Seed, status, stat stages, current HP (HP-scaling moves and abilities), weight (weight-based moves), abilities, held items, critical hits and doubles spread damage.
- Any Champions species or Mega must be selectable on either side, with its base stats, abilities and weight.
- A team slot, a tournament roster member (with the paste's set when present) and a box entry must be sendable to the calculator.
- Status moves with a known effect (self boosts, screens, Tailwind, weather, terrain, status infliction) must be applicable to the calculation with one toggle.
- The user must be able to sweep every Champions species against the attacker and see each classified as Crushed, Threat, Wall, Mitigated or Neutral from the hits each side needs and the speed order, with the opponent's most used tournament moves available as its set.
- The last calculation must be remembered between launches.
- The engine must be verified against the Smogon damage calculator's Champions module.

## Quality and Usability Requirements

### QR-1 Fast lookup workflow
- Adding a Pokemon should feel immediate and require minimal user input.

### QR-2 Clear empty and error states
- The UI should explain when a Pokemon is missing, duplicated, or cannot be loaded.

### QR-3 Responsive layout
- The GUI should work on typical desktop screen sizes and degrade gracefully on smaller windows.
- Implemented: the window works from about 900px up; the rail compacts below 1280px and side panels overlay below 1024px.

### QR-4 Data persistence
- Box and team data should persist between sessions.

### QR-5 Consistent naming
- The system should normalize Pokemon names to a stable internal identity so duplicate wording does not create duplicate entries.
