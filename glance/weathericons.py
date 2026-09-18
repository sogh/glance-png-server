"""Weather icons, drawn with primitives rather than typed as pixel art.

Circles and clouds are painful to hand-author character by character and easy
to describe as overlapping discs, which is the opposite of the sweatpants.

Every icon draws inside a square box of the given size, and
`test_every_icon_stays_inside_its_box` holds all of them to it. The box is
not decoration: the forecast column lays out against it, with the weekday
directly above and the high directly below, so an icon that spills a few rows
either way lands *in* the text rather than beside it. Four of these used to.
"""

from __future__ import annotations

from typing import Callable

from .palette import dim

BOLT = (
    "..##.",
    ".##..",
    "####.",
    "..##.",
    ".##..",
    ".#...",
)


def _cloud(c, x: int, y: int, size: int, color, base_shift: int = 0) -> None:
    """Three overlapping discs on a flat bottom."""
    w = size
    bottom = y + int(w * 0.72) + base_shift
    r_big = max(2, int(w * 0.26))
    r_small = max(2, int(w * 0.19))
    # The left disc is placed by proportion but sized by a floor, so below
    # about 24px the floor won.  It hung a pixel off the left edge of the box
    # -- which on the panel meant six of the eight conditions inked one column
    # inside the margin that is supposed to separate this pane from its
    # neighbour.
    left = x + max(int(w * 0.18), r_small)
    c.disc(x + int(w * 0.38), y + int(w * 0.44), r_big, color)
    c.disc(x + int(w * 0.66), y + int(w * 0.50), r_small, color)
    c.disc(left, y + int(w * 0.54), r_small, color)
    c.fill_rect(x + int(w * 0.14), y + int(w * 0.50), int(w * 0.60), bottom - (y + int(w * 0.50)), color)


def _sun_geometry(size: int) -> tuple[int, int, int]:
    """Disc radius, ray gap and ray reach for a sun that fits its own box.

    Both floors here have bitten. Too short a reach and `range(gap, reach)` is
    empty, so the sun loses its rays entirely and reads as a full moon --
    which is what happened at the forecast icon size. Too long and the rays
    overrun the box: `clear` put ink a row below and a column right of its own
    edge, and `partly`, which shrinks the sun and lifted it clear of the top,
    put three rows of rays up into the weekday label.

    Below about 10px the two cannot both be had, and containment wins: the sun
    keeps its disc and loses its rays. That is the right way round, because at
    that size the rays are what turn a forecast column into noise anyway.
    """
    half = (size - 1) // 2                  # ink may reach this far from centre
    r = max(2, min(max(3, int(size * 0.24)), half - 2))
    gap = r + 2
    reach = min(max(gap + 2, int(size * 0.5)), half + 1)
    return r, gap, reach


def sun(c, x, y, size, night=False, background="black"):
    color = "sky" if night else "amber"
    cx, cy = x + size // 2, y + size // 2
    r, gap, reach = _sun_geometry(size)
    if night:
        # Crescent: cut the disc with a second one in the background colour.
        # It has to be the panel's real background rather than a literal
        # black, or setting `background` on the scene puts a black bite out
        # of the moon.
        c.disc(cx, cy, r + 1, "white")
        # The bite matches the disc rather than exceeding it: one wider joins
        # up the lower horn, which at small radii tapers to a detached pixel,
        # but thins the whole crescent to a smear in the process. A fat moon
        # with a one-pixel horn reads better than a spindly continuous one.
        c.disc(cx + r // 2 + 1, cy - 1, r, background)
        return
    c.disc(cx, cy, r, color)
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        for step in range(gap, reach):
            c.pixel(cx + dx * step, cy + dy * step, dim(color, 0.9))


def clear_day(c, x, y, size, night=False, background="black"):
    sun(c, x, y, size, night=False, background=background)


def clear_night(c, x, y, size, night=True, background="black"):
    sun(c, x, y, size, night=True, background=background)


def partly(c, x, y, size, night=False, background="black"):
    """Sun -- or moon -- behind a cloud, both inside the box.

    `night` used to be dropped on the floor here, so a partly cloudy 2am drew
    full sunshine.
    """
    # A moon needs more clearance than a sun. A sun reads from the sliver of
    # disc and the rays above the cloud; a crescent is mostly the space it is
    # cut out of, so the same composition covered all but a nub of it and read
    # as neither moon nor sun. At night the moon shrinks and the cloud drops,
    # which puts the whole crescent above the cloud line. The cloud also goes
    # grey: a white moon behind a white cloud is one white blob.
    s = int(size * (0.55 if night else 0.72))
    sun(c, x + (size - s) // 2, y, s, night, background)
    # Drop the cloud as far as asked, but never past the box: `_cloud` runs
    # 0.72 of the size below wherever it is put, and asking for 0.34 of a 22px
    # box put its flat bottom a row outside. Clamping says that in one place
    # rather than leaving the two factors to be kept in agreement by hand.
    drop = min(int(size * (0.34 if night else 0.18)), size - 1 - int(size * 0.72))
    _cloud(c, x, y + drop, size, "grey" if night else "white")


def cloudy(c, x, y, size, night=False, background="black"):
    _cloud(c, x, y, size, "white")


def _drops(c, x, y, size, color, shape="line"):
    top = y + int(size * 0.76)
    for i, dx in enumerate((0.24, 0.46, 0.68)):
        px = x + int(size * dx)
        if shape == "line":
            for k in range(3):
                c.pixel(px - k, top + k, color)
        else:                      # snow: a small cross
            c.pixel(px, top + 1, color)
            c.pixel(px - 1, top + 1, color)
            c.pixel(px + 1, top + 1, color)
            c.pixel(px, top, color)
            c.pixel(px, top + 2, color)


def rain(c, x, y, size, night=False, background="black"):
    _cloud(c, x, y - 2, size, "grey")
    _drops(c, x, y - 2, size, "sky", "line")


def drizzle(c, x, y, size, night=False, background="black"):
    _cloud(c, x, y - 2, size, "grey")
    _drops(c, x, y - 2, size, dim("sky", 0.7), "line")


def snow(c, x, y, size, night=False, background="black"):
    _cloud(c, x, y - 2, size, "grey")
    _drops(c, x, y - 2, size, "white", "cross")


def thunder(c, x, y, size, night=False, background="black"):
    """Cloud above, bolt below -- and the pair sized to the box.

    The cloud used to be lifted three rows to make room for the bolt, which
    put it above the top edge. Shrinking the cloud instead buys the same room
    from the inside.
    """
    cloud = int(size * 0.82)
    _cloud(c, x + (size - cloud) // 2, y, cloud, "grey")
    bx = x + size // 2 - 2
    by = y + min(int(size * 0.60), size - len(BOLT))
    for row, line in enumerate(BOLT):
        for col, ch in enumerate(line):
            if ch == "#":
                c.pixel(bx + col, by + row, "yellow")


def fog(c, x, y, size, night=False, background="black"):
    """Four bars, spread to fill the box.

    The spacing was a flat 4px from a fixed start: right for the 22px icon it
    was drawn against, and five rows too deep at 12px, where the bottom bar
    landed squarely on the forecast high.
    """
    bars, thick = 4, 2
    step = max(thick + 1, (size - thick) // (bars - 1))
    top = y + max(0, (size - (thick + (bars - 1) * step)) // 2)
    for i, (inset, width) in enumerate(((0.10, 0.80), (0.20, 0.64), (0.06, 0.86), (0.24, 0.56))):
        c.fill_rect(x + int(size * inset), top + i * step,
                    int(size * width), thick, dim("white", 0.55 + 0.1 * i))


ICONS: dict[str, Callable] = {
    "clear": clear_day,
    "partly": partly,
    "cloudy": cloudy,
    "fog": fog,
    "drizzle": drizzle,
    "rain": rain,
    "snow": snow,
    "thunder": thunder,
}


def draw(c, condition: str, x: int, y: int, size: int = 22, night: bool = False,
         background: str = "black") -> None:
    if condition == "clear" and night:
        clear_night(c, x, y, size, background=background)
        return
    ICONS.get(condition, cloudy)(c, x, y, size, night, background)
