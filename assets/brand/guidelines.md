# Champions MetaDesk Studio: logo usage

## The idea
Two sides of a matchup split on one sharp 30° cut: the **plan** and the **play** slide past each other. Inside the
plan half, the **echo** (a second, thinner cut at the same angle) and the **hexagon** (the team of six) are the hit
that lands first. On the crimson tile the mark is white and the hit is graphite.

## Versions
| File | Use |
|---|---|
| `tile.svg` | **Primary.** App icon, window and taskbar icon, avatar, social |
| `tile-small.svg` | The tile at **32 px and below** (favicon, menu rail): disc, cut and slide only, wider gap |
| `lockup-horizontal.svg` / `-dark.svg` | README header, release pages, website header |
| `lockup-stacked.svg` / `-dark.svg` | Square spaces: splash screens, social cards |
| `symbol.svg` / `symbol-on-dark.svg` | The mark without its tile, where a tile can't fit (inline, patterns) |
| `symbol-small.svg` | The free-standing mark at 32 px and below |
| `symbol-black.svg` / `symbol-white.svg` | One-colour: print, embossing, single-colour contexts |
| `wordmark.svg` | “MetaDesk” alone, where the full lockup is too wide |
| `icon-full-bleed.svg`, `icon-maskable.svg` | Platform icon sources (iOS rounds, Android masks) |

## Colour
| Name | HEX | RGB | CMYK (approx.) | Used for |
|---|---|---|---|---|
| Crimson | `#D7263D` | 215, 38, 61 | 0/82/72/16 | the tile; the symbol on light backgrounds; the CHAMPIONS line |
| Crimson on dark | `#F0384F` | 240, 56, 79 | 0/77/67/6 | the hit (echo + hexagon) of the free-standing symbol on dark backgrounds |
| Graphite | `#26262B` | 38, 38, 43 | 12/12/0/83 | the hit on the tile; the wordmark on light backgrounds |
| White | `#FFFFFF` | 255, 255, 255 | 0/0/0/0 | the mark on the tile; the wordmark on dark backgrounds |
| Studio grey | `#6B6B73` | 107, 107, 115 | 7/7/0/55 | “Studio” on light backgrounds (#B4B4BC on dark) |

The tile is always crimson with a white mark. The hit is graphite on the tile and on light backgrounds, crimson on dark ones.
Contrast: white mark on the crimson tile 4.96:1 · crimson on white 4.96:1 · the tile on the app navy 3.8:1 (a solid shape, above the 3:1 for graphics) · crimson-on-dark `#F0384F` on navy 4.83:1 · the graphite hit on crimson 3.04:1.

## Clear space and minimum size
- **Clear space:** at least the tile's corner radius (¼ of the tile's width) on every side; for the lockups,
  the height of the “M”.
- **Minimum sizes:** tile 16 px (use `tile-small` up to 32 px) · horizontal lockup 24 px tall · stacked lockup 64 px
  tall · free-standing symbol 20 px.

## Typography
The wordmark is **Roboto** Bold (“MetaDesk”, tracked −1.2 %) and Regular (“Studio”), with “CHAMPIONS” in Medium,
tracked +32 %. Letters are outlined, and the D carries a short cut at the mark's 30°. Roboto is Apache-2.0 licensed;
no font is needed to use the files.

## Don't
- Recolour the tile, swap the halves' colours, or add a second colour to the halves (red + blue reads as an
  emulator mark).
- Put the full mark below 32 px (use the small cut), or stretch, rotate, outline or add shadows and gradients.
- Fill the echo or hexagon in anything but graphite (on the tile and on light) or crimson (on dark).
- Place the free-standing crimson symbol on a busy or red background: use the tile or the white version.
- Rebuild the wordmark in a live font.

## Notes
The mark is original. It isn't affiliated with Nintendo, Game Freak, Creatures Inc. or The Pokémon Company.
A professional trademark search is recommended before wider use.
