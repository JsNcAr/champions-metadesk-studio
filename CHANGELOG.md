# Changelog

All notable changes to Champions MetaDesk Studio. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Add entries under **Unreleased** in the same PR as the change; that section becomes
the next release's description. See [docs/releasing.md](docs/releasing.md#writing-the-release-description)
for the headings and style.

## [Unreleased]

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
