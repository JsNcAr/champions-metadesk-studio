# Changelog

All notable changes to Champions MetaDesk Studio. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Add entries under **Unreleased** in the same PR as the change; that section becomes
the next release's description. See [docs/releasing.md](docs/releasing.md#writing-the-release-description)
for the headings and style.

## [Unreleased]

### Added
- **Formats and mechanics.** A team is built for a format, and the team builder shows only the
  mechanics that format has. Pokémon Champions (Regulations M-A to M-C) has Mega Evolution
  and no Terastallization, so the Tera dropdown is gone from the slot cards. **Settings ›
  Format & mechanics** sets the default format and creates custom ones: singles or doubles,
  Mega Evolution and Terastallization on or off, one Mega per team, Item Clause. Z-Moves and
  Dynamax are listed as not supported yet. The chip next to the team name picks a team's own
  format.
  - Without Mega Evolution a Mega Stone no longer changes the form, the item picker hides
    the stones, and the calculator hides its Base/Mega switch (it follows the default
    format, which also decides Singles or Doubles when the calculator is reset).
  - Tera types are kept: export writes the `Tera Type:` line only when the team's format
    has Terastallization, and imports still read it.

### Changed
- The team export dialog says "Stat points" instead of "EVs". Copy and Publish still write
  them on Showdown's `EVs:` line, which is what Showdown and Poképaste read, and pasting a
  "Stat points:" line back into the app works too.
- Settings' "Battle format" dropdown is now called **Tournament filter**: it filters
  tournament data (Doubles only, All, Singles only) and is separate from the formats above.

## [0.4.0] - 2026-09-21

### Added
- **Rival teams in the calculator.** A switch above the opponents list shows a rival team
  instead: each member is coloured against your attacker, and one click loads it as the
  Defender (your team is then coloured against it too).
  - **In a battle**, Team preview (Ctrl+B) takes the six species you see and fills each with
    its most used tournament set. What you set on a rival in the Defender panel (item,
    ability, moves, nature, stat points) is kept for the rest of the battle, and its ? mark
    stops listing what you have seen.
  - **Presets** keep teams to plan against or battle again. **Load team…** saves one from
    your own teams (Teams view), a Showdown paste or a Poképaste link, and Meta saves any
    tournament team from its calculator menu. **Use in battle** loads a preset into the
    current battle: what the battle reveals goes to the battle's copy, and the preset only
    changes through "Save Defender to …".
  - **Team vs team** shows your active team against theirs, every pairing coloured, with
    how many rivals each of your Pokémon answers and how many of yours each rival threatens.

### Fixed
- Ctrl+F in the calculator did not focus the species search.
- The calculator's **?** buttons only showed a tooltip on hover and did nothing when
  clicked; they now open the explanation.

## [0.3.1] - 2026-09-21

### Fixed
- The Teams **Export** button did nothing: its menu (Copy Showdown text, Show export /
  publish…) never opened. The Box detail panel's **Add to team** menu had the same problem.
- Links that open a website did nothing: the Meta event results and Poképaste links, and
  the Poképaste link shown after publishing a team.

## [0.3.0] - 2026-09-21

### Added
- **Your team, rated against the rival.** Put a Pokémon in the Calc's Defender panel and each
  member of your active team is coloured by how it fares against it, using the opponents
  list's colours: Crushed (green), Mitigated (blue), Neutral, Wall (amber), Threat (red).
  Hover a member for its best move each way and who moves first. The colours follow the
  field (weather, screens, Trick Room…) and your team edits.

## [0.2.3] - 2026-09-21

### Added
- The project is now open source under the MIT License.
- Settings → About shows the license and a trademark disclaimer: this is an unofficial fan
  tool, not affiliated with Nintendo, Game Freak, Creatures Inc. or The Pokémon Company.

### Changed
- The downloadable Windows, macOS and Linux archives include the license and third-party
  notices.

### Performance
- Selecting a Pokémon in a full Box is instant: it used to redraw the whole Box (about a
  second with 250 entries), and now redraws only the two cards and the detail panel.

### Fixed
- Dropdown values (the team selector, abilities, every Meta filter), text typed into fields
  and some labels were nearly black on the dark background.
- The damage calculator could forget the last change made just before closing the app.
- Z Mega Evolutions show as "Mega Garchomp Z" rather than "Garchomp-Mega-Z" in the Box.
- Opponent names in the Calc opponents list were cut off at medium window widths.

## [0.2.2] - 2026-09-21

A calculator that answers first: the matchup is always in view, and the field takes a
third less room.

### Added
- **Calc matchup bar** under the page title: each side's best move on the other, its
  damage and KO chance, and who moves first. It stays visible while you scroll.
- **Clear** in the field strip resets weather, terrain, rooms, side conditions, stat
  stages, statuses and activated abilities, keeping both Pokémon as they are. It can be
  undone.
- **Fill with top moves** for a Pokémon with no moves: tournament favourites, or the
  hardest hitters against the other side.
- Reset in Calc can be undone.

### Changed
- Calc shows the moves and their damage right under each Pokémon; the spread and the new
  "Stages & status" section follow and can be collapsed (a collapsed section still shows
  what is active, like "+2 Atk · Burned").
- The team/box rail, the calculator and the opponents list scroll separately, so the rail
  and the opponents stay in view.
- The field strip is always open but about a third smaller: Tailwind sits with each
  side's conditions, and Helping Hand and Friend Guard are hidden in Singles.
- In windows narrower than 1280px the attacker and defender panels stack instead of
  squeezing.
- The ability "Activate" chip and "Allies fainted" only appear for the abilities they
  affect.

### Performance
- Dragging a spread slider recomputes, saves and re-runs the opponents list once when
  you let go, instead of on every step (11 recomputes and 22 panel redraws → 1 and 1).

### Fixed
- Chip labels across the app were nearly black on dark chips and looked disabled.
- Calc's species search now says when nothing matches instead of doing nothing.
- The Calc page caption disappeared after the first result.
- The opponents list and the panels showed the speed arrow the opposite way round.
- The box list in Calc stopped at 40 Pokémon without saying so; it now offers "Show more".
- The HP box in Calc ignored a value typed without pressing Enter.

## [0.2.1] - 2026-09-21

### Fixed
- Importing a box file onto Pokémon you already have kept their tags and favourites
  but dropped the notes, while reporting them as updated.
- Calc showed the species name twice in both the attacker and defender panels.
- Settings reported "1 sprite cached (0 KB)" before any sprite was downloaded, and
  clearing the sprite cache deleted more than the sprites.

## [0.2.0] - 2026-09-21

Faster everywhere, and sprites finally work in the browser build.

### Added
- Release tooling: `scripts/release.py` and a release workflow that tests, checks the
  version, builds all platforms and publishes these notes.

### Performance
- The window opens straight away, even on first launch; catalogues download in the
  background behind a "Setting up" banner instead of blocking for ~20 s.
- Switching between Box, Teams, Meta and Calc is near-instant and crossfades; returning
  to a section no longer rebuilds it, and sections are prepared while the app is idle.
- Box filter results appear ~0.35 s after you stop typing instead of ~2.4 s; the Box
  draws its first screenful sooner and card clicks are cheaper.
- Much faster Meta filtering ("N missing from my box": 2.0 s → 0.2 s), move usage,
  teammate suggestions and team loading on large tournament databases.
- Faster start-up once the database is migrated, and no delay when closing the window.

### Fixed
- Sprites are served from the local cache again, and show at all in the browser
  build (they were blocked there by its cross-origin policy).
- "Sync sprites" in Settings failed on any non-empty box.
- Keyboard focus (Tab) could land in the Box while another section was on screen.
- Official events whose team lists Victory Road posts late (e.g. 2027 Baltimore
  Regionals) were given up on after 14 days; they are now retried for 45 days, with a
  clear "no team list published yet" message.
- The app no longer fails to open when it cannot create its sprite cache folder
  (a macOS app opened from Finder starts in the read-only `/`).
- Settings → About shows the real version in packaged builds.

## [0.1.0] - 2026-09-14

First public release: Box roster, team builder, tournament meta explorer, Champions
damage calculator, and desktop builds for Linux, Windows and macOS.
