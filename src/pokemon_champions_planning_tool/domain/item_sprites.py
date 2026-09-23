"""Item icons from Pokémon Showdown's item sheet, for items PokéAPI has no sprite for.

PokéAPI has no art for the Champions-only Mega Stones (Excadrite, Absolite Z…) and a few
others (Fairy Feather). Showdown draws every item from one sheet of 24×24 cells, 16 per
row, and each item's ``spritenum`` in its data files picks the cell. Such an item's
``sprite_url`` is the sheet URL with the cell number as the fragment
("…/itemicons-sheet.png#553"); ``components.item_icon`` crops it.
"""

from __future__ import annotations

ITEM_SHEET_URL = "https://play.pokemonshowdown.com/sprites/itemicons-sheet.png"
SHEET_COLUMNS = 16
CELL = 24
SHEET_WIDTH = SHEET_COLUMNS * CELL      # 384
SHEET_HEIGHT = 1152                     # 48 rows; Showdown grows it as items are added


def sheet_url(spritenum: int) -> str:
    return f"{ITEM_SHEET_URL}#{int(spritenum)}"


def sheet_cell(url: str | None) -> int | None:
    """The cell number of a sheet URL, or None for an ordinary image URL."""
    if not url or not url.startswith(ITEM_SHEET_URL + "#"):
        return None
    try:
        return int(url.rsplit("#", 1)[1])
    except ValueError:
        return None


def cell_offset(spritenum: int) -> tuple[int, int]:
    """(x, y) of a cell's top-left corner on the sheet, in sheet pixels."""
    return (spritenum % SHEET_COLUMNS) * CELL, (spritenum // SHEET_COLUMNS) * CELL


__all__ = ["CELL", "ITEM_SHEET_URL", "SHEET_HEIGHT", "SHEET_WIDTH", "cell_offset", "sheet_cell", "sheet_url"]
