"""Wind on its own panel.

Wind never fitted the weather panel. Its third line already carries the
precipitation chance and the AQI, which leaves seventeen pixels beside three
forecast columns -- enough for `W22` but not for `SW22`, so the reading would
have appeared on a westerly and vanished on a south-westerly. A number that
comes and goes with the compass reads as a broken sensor, not a shortage of
room, so wind got a panel instead.

The graphic is the point. A speed in miles per hour means something only if
you already know the scale, and at a glance across a kitchen nobody is
converting 31 into "hold onto the recycling bin". The streaks answer that
without being read: more of them, longer, as it blows harder.
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..layout import MARGIN, fits, row
from .base import Param, RenderContext, register

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# Beaufort, collapsed to the six steps that are worth telling apart on a
# 32px panel. The ceiling is the top of the band, in mph.
BANDS = (
    (3, "CALM", "grey"),
    (12, "LIGHT", "sky"),
    (24, "BREEZY", "mint"),
    (38, "WINDY", "amber"),
    (54, "GALE", "orange"),
    (999, "STORM", "red"),
)


def band_for(speed: float) -> tuple[int, str, str]:
    """Level 0-5, its name, and the colour that carries it."""
    for level, (ceiling, name, color) in enumerate(BANDS):
        if speed <= ceiling:
            return level, name, color
    return len(BANDS) - 1, BANDS[-1][1], BANDS[-1][2]


def point_for(degrees: int | None) -> str:
    """The compass point the wind is coming FROM."""
    if degrees is None:
        return ""
    return COMPASS[int(degrees / 45 + 0.5) % 8]


def streak_lengths(budget: int, level: int) -> list[int]:
    """How long each motion line is, longest first in the middle.

    Measured before anything is drawn so the row can be centred on the art
    that actually appears. Reserving the full budget at CALM -- when the lines
    are stubs -- pushed the whole group a dozen pixels right of centre.

    Lengths are staggered rather than equal: a stack of identical rules reads
    as a barcode, and the ragged right-hand edge is what makes it move.
    """
    count = min(2 + level, 5)              # 2 at calm; 5 lines is 20px of 32
    reach = 0.42 + 0.58 * (level / (len(BANDS) - 1))
    out = []
    for index in range(count):
        middle = abs(index - (count - 1) / 2) / max(1, (count - 1) / 2)
        out.append(max(4, int(round(budget * reach * (1 - 0.35 * middle)))))
    return out


def _streaks(c: Canvas, x: int, y: int, lengths: list[int], color) -> None:
    step = 4
    top = y - (len(lengths) - 1) * step // 2
    for index, length in enumerate(lengths):
        c.hline(x, top + index * step, length, color)


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    source = getattr(ctx, "weather", None)
    current = source.current() if source else None
    if current is None or current.wind is None:
        return False
    floor = float(params.get("floor", 0) or 0)
    return current.wind >= floor


@register("wind", available=_available,
          description="Wind speed, direction and gusts, with an intensity graphic",
          params=[
              Param("floor", "number", 0, minimum=0, maximum=60,
                    help="Hide the panel below this speed; 0 always shows it"),
              Param("gusts", "bool", True, help="Show the gust when it beats the wind"),
              Param("band", "bool", True, help="Name the strength: CALM, BREEZY, GALE"),
              Param("direction", "bool", True, help="Show the compass point"),
              Param("margin", "number", MARGIN, minimum=0, maximum=40,
                    help="Smallest gap at the left and right edges"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_wind(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))

    source = getattr(ctx, "weather", None)
    current = source.current() if source else None
    if current is None or current.wind is None:
        c.centered("no wind data", "grey", "3x5")
        return c

    big, small = get_font("5x7"), get_font("3x5")
    margin = int(params.get("margin", MARGIN))
    level, name, color = band_for(current.wind)

    speed = f"{current.wind:.0f}"
    unit = current.wind_unit.upper()
    point = point_for(current.wind_dir) if bool(params.get("direction", True)) else ""
    # A gust is only worth the space when it is a good step above the
    # sustained wind. A ratio alone reports "G4" on a 2mph afternoon, which is
    # both true and useless.
    gust = ""
    if (bool(params.get("gusts", True)) and current.gusts is not None
            and current.gusts - current.wind >= 5):
        gust = f"G{current.gusts:.0f}"

    # Three blocks: the graphic, the reading, and the detail beside it. Each
    # is measured before anything is drawn, so the row can be centred as one
    # group and the blank falls at the two edges.
    lengths = streak_lengths(46, level)
    icon_w = max(lengths)
    speed_w = big.measure(speed) * 2 + 3 + small.measure(unit)
    band_w = small.measure(name) if bool(params.get("band", True)) else 0
    detail_w = max(small.measure(point), small.measure(gust)) if (point or gust) else 0

    # Shed rather than cross the margin. On a single 64px module all three
    # blocks cannot stand, so the detail goes first, then the graphic, then
    # the band -- in the reverse order of how much each is worth. The speed
    # is the one thing that never goes.
    gap = 10
    for show_icon, show_detail, show_band in ((1, 1, 1), (1, 0, 1),
                                              (0, 0, 1), (0, 0, 0)):
        read_w = max(speed_w, band_w if show_band else 0)
        widths = [w for w in (icon_w if show_icon else 0, read_w,
                              detail_w if show_detail else 0) if w]
        if fits(c.width, widths, gap, margin):
            break

    xs = row(c.width, widths, gap, margin)
    names = [n for n, w in (("icon", icon_w if show_icon else 0),
                            ("read", read_w),
                            ("detail", detail_w if show_detail else 0)) if w]
    slot = dict(zip(names, xs))

    if "icon" in slot:
        _streaks(c, slot["icon"], 15, lengths, color)

    x = slot["read"]
    c.text(x, 6, speed, color, big, "left", None, 2)
    c.text(x + big.measure(speed) * 2 + 3, 13, unit, "grey", small)
    if band_w and show_band:
        c.text(x, 23, name, color, small)

    if "detail" in slot:
        x = slot["detail"]
        if point:
            c.text(x, 9, point, "white", small)
        if gust:
            c.text(x, 18, gust, "amber", small)
    return c
