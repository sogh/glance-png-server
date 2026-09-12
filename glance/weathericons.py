"""Weather icons, drawn with primitives rather than typed as pixel art.

Circles and clouds are painful to hand-author character by character and easy
to describe as overlapping discs, which is the opposite of the sweatpants.
Every icon draws inside a square box of the given size.
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
    c.disc(x + int(w * 0.38), y + int(w * 0.44), r_big, color)
    c.disc(x + int(w * 0.66), y + int(w * 0.50), r_small, color)
    c.disc(x + int(w * 0.18), y + int(w * 0.54), r_small, color)
    c.fill_rect(x + int(w * 0.14), y + int(w * 0.50), int(w * 0.60), bottom - (y + int(w * 0.50)), color)


def sun(c, x, y, size, night=False):
    color = "sky" if night else "amber"
    cx, cy = x + size // 2, y + size // 2
    r = max(3, int(size * 0.24))
    if night:
        # Crescent: cut the disc with a second one in the background colour.
        c.disc(cx, cy, r + 1, "white")
        c.disc(cx + r // 2 + 1, cy - 1, r, "black")
        return
    c.disc(cx, cy, r, color)
    gap = r + 2
    # reach must clear the gap or range() is empty and the sun loses its rays
    # entirely -- which is exactly what happened at the forecast icon size.
    reach = max(gap + 2, int(size * 0.5))
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        for step in range(gap, reach):
            c.pixel(cx + dx * step, cy + dy * step, dim(color, 0.9))


def clear_day(c, x, y, size):   sun(c, x, y, size, night=False)
def clear_night(c, x, y, size): sun(c, x, y, size, night=True)


def partly(c, x, y, size):
    sun(c, x, y - int(size * 0.16), int(size * 0.72))
    _cloud(c, x, y + int(size * 0.18), size, "white")


def cloudy(c, x, y, size):
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


def rain(c, x, y, size):
    _cloud(c, x, y - 2, size, "grey")
    _drops(c, x, y - 2, size, "sky", "line")


def drizzle(c, x, y, size):
    _cloud(c, x, y - 2, size, "grey")
    _drops(c, x, y - 2, size, dim("sky", 0.7), "line")


def snow(c, x, y, size):
    _cloud(c, x, y - 2, size, "grey")
    _drops(c, x, y - 2, size, "white", "cross")


def thunder(c, x, y, size):
    _cloud(c, x, y - 3, size, "grey")
    bx = x + size // 2 - 2
    by = y + int(size * 0.62)
    for row, line in enumerate(BOLT):
        for col, ch in enumerate(line):
            if ch == "#":
                c.pixel(bx + col, by + row, "yellow")


def fog(c, x, y, size):
    for i, (inset, width) in enumerate(((0.10, 0.80), (0.20, 0.64), (0.06, 0.86), (0.24, 0.56))):
        c.fill_rect(x + int(size * inset), y + int(size * 0.26) + i * 4,
                    int(size * width), 2, dim("white", 0.55 + 0.1 * i))


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


def draw(c, condition: str, x: int, y: int, size: int = 22, night: bool = False) -> None:
    if condition == "clear" and night:
        clear_night(c, x, y, size)
        return
    ICONS.get(condition, cloudy)(c, x, y, size)
