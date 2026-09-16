"""Small pixel-art sprites, authored the same way as the fonts.

Each sprite is rows of characters mapping to colours: '.' is transparent and
every other character is a palette entry. Editing a sprite means editing the
picture, which is the point -- at this size, drawing in a paint program and
importing is more trouble than typing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .palette import RGB, parse


@dataclass(frozen=True)
class Sprite:
    rows: tuple[str, ...]
    palette: dict[str, str] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def height(self) -> int:
        return len(self.rows)

    def color_for(self, ch: str, override: dict[str, str] | None = None) -> RGB | None:
        if ch == ".":
            return None
        table = {**self.palette, **(override or {})}
        value = table.get(ch)
        return parse(value) if value else None


# Grey marl sweatpants: elastic waistband, drawstring, baggy through the
# thigh, elastic cuffs.
SWEATPANTS = Sprite(
    rows=(
        "------------------------",   # elastic waistband
        "------------------------",
        "------------------------",
        "##########+##+##########",   # drawstring
        "##########+##+##########",
        "##########+##+##########",
        "########################",
        "###########..###########",   # crotch
        "##########....##########",
        "##########....##########",
        ".#########....#########.",   # and from here the taper, which is the
        ".#########....#########.",   # whole silhouette: baggy at the hip,
        "..########....########..",   # narrow at the ankle. Without it this
        "..########....########..",   # reads as shorts.
        "..########....########..",
        "...#######....#######...",
        "...#######....#######...",
        "...#######....#######...",
        "....######....######....",
        "....######....######....",
        "....######....######....",
        "....######....######....",
        "....------....------....",   # gathered cuffs
        "....------....------....",
        "....------....------....",
    ),
    palette={
        "#": "#8c8c91",     # the marl itself
        "-": "#5a5a5f",     # waistband and cuffs, a shade darker
        "+": "#d7d7dc",     # drawstring
    },
)


# An orb web. Built from eight spokes and two rings rather than drawn freehand,
# because a web is geometry and hand-placed pixels wobble.
#
# Two things make it read at this size. The hub is left OPEN: with the spokes
# carried all the way in they merge into a solid bar across the middle and the
# whole thing reads as a wheel. And there are only two rings -- three filled the
# gaps between them and it turned to mush at 1:1.
SPIDERWEB = Sprite(
    rows=(
        "............##...........",
        "..........###.##.........",
        "........##..#...##.......",
        "......##....#.....##.....",
        "....##......#.......#....",
        "...#.#.....###.....##....",
        "...#..#..##.#.##..#..#...",
        "..#....##...#...##...#...",
        "..#....##...#...##....#..",
        ".#....#..#.....#..#...#..",
        ".#....#...........#....#.",
        "#....#.............#...#.",
        "#########.......#########",
        ".#...#.............#....#",
        ".#....#...........#....#.",
        "..#...#..#.....#..#....#.",
        "..#....##...#...##....#..",
        "...#...##...#...##....#..",
        "...#..#..##.#.##..#..#...",
        "....##.....###.....#.#...",
        "....#.......#......##....",
        ".....##.....#....##......",
        ".......##...#..##........",
        ".........##.###..........",
        "...........##............",
    ),
    palette={"#": "#dcdce4"},      # old silk, not quite white
)


SPRITES: dict[str, Sprite] = {
    "sweatpants": SWEATPANTS,
    "spiderweb": SPIDERWEB,
}


def get_sprite(name: str) -> Sprite | None:
    return SPRITES.get(str(name).strip().lower())


def draw_sprite(canvas, sprite: Sprite, x: int, y: int,
                override: dict[str, str] | None = None, scale: int = 1) -> int:
    """Paste a sprite. Returns the width drawn."""
    scale = max(1, int(scale))
    for row_index, row in enumerate(sprite.rows):
        for col_index, ch in enumerate(row):
            color = sprite.color_for(ch, override)
            if color is None:
                continue
            if scale == 1:
                canvas.pixel(x + col_index, y + row_index, color)
            else:
                canvas.fill_rect(x + col_index * scale, y + row_index * scale,
                                 scale, scale, color)
    return sprite.width * scale
