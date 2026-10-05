"""The tide: where the water is now, which way it is going, and the next turns.

Three blocks, in the order a glance wants them. The graph says the most with
the least reading -- where in the cycle we are, and how big today's swing is
-- so it comes first. Then the height and its direction. Then a small table
for whoever is actually planning around it: the next high and low, and under
them the day's highest and lowest water.

The day's pair is not a repeat of the next pair. Puget Sound's tide is mixed,
so the next high is as likely to be the small one as the big one, and by
afternoon the morning's minus tide -- the one worth walking out to -- has
already gone from "next" while still being the day's low.

The graph spans six hours back and eighteen forward, so "now" sits a quarter
of the way in and most of the width is spent on what is coming. A window
centred on now gives half the panel to water that has already gone.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..layout import MARGIN, fits, row
from ..palette import mix
from .agenda import fmt_time
from .base import Param, RenderContext, register

BEHIND = timedelta(hours=6)
AHEAD = timedelta(hours=18)

WATER = "blue"
SURFACE = "cyan"
RISING = "mint"
FALLING = "sky"

# Within this of a turn, the water is effectively slack, and "RISING" would
# be true by a centimetre and misleading by the look of the beach.
SLACK = timedelta(minutes=20)


def height_text(height: float) -> str:
    """One decimal, and no "-0.0" for a low that rounds to nothing."""
    text = f"{height:.1f}"
    return "0.0" if text == "-0.0" else text


def curve(tides, now: datetime, width: int, top: int, bottom: int) -> list[int | None]:
    """The water's y for each column of the graph, None where it is unknown.

    Scaled to the extremes inside the window rather than the whole fetch, so
    a neap day still fills the box -- the shape is the information, and the
    numbers beside it give the size.
    """
    start, span = now - BEHIND, BEHIND + AHEAD
    heights = [tides.height_at(start + span * (x / max(1, width - 1)))
               for x in range(width)]
    known = [h for h in heights if h is not None]
    if not known:
        return [None] * width
    low, high = min(known), max(known)
    scale = (bottom - top) / (high - low) if high > low else 0
    return [None if h is None else int(round(bottom - (h - low) * scale))
            for h in heights]


def _graph(c: Canvas, x0: int, width: int, tides, now: datetime) -> None:
    top, bottom = 4, 27
    ys = curve(tides, now, width, top, bottom)
    deep = mix(WATER, "black", 0.55)
    for dx, y in enumerate(ys):
        if y is None:
            continue
        # The body shades darker with depth, so the fill reads as water and
        # not as a bar chart.
        for yy in range(y + 1, bottom + 2):
            c.pixel(x0 + dx, yy, mix(WATER, deep, (yy - y) / (bottom + 2 - y)))
        c.pixel(x0 + dx, y, SURFACE)
    # Now: a dotted rule, and the surface at that moment in white.
    nx = x0 + int(round((width - 1) * BEHIND / (BEHIND + AHEAD)))
    for yy in range(top - 3, bottom + 2, 2):
        c.pixel(nx, yy, "grey")
    y = ys[nx - x0]
    if y is not None:
        c.fill_rect(nx - 1, y - 1, 3, 3, "white")


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    source = getattr(ctx, "tides", None)
    tides = source.current() if source else None
    return tides is not None and tides.height_at(ctx.now) is not None


@register("tides", available=_available,
          description="The tide now, which way it is going, and the next highs and lows",
          params=[
              Param("count", "number", 2, minimum=1, maximum=4,
                    help="How many upcoming highs and lows to list (2 at most "
                         "beside the day's range)"),
              Param("day", "bool", True,
                    help="Also list the day's highest and lowest tide"),
              Param("graph", "bool", True,
                    help="Draw the water level from six hours ago to eighteen ahead"),
              Param("hour24", "bool", False, help="24-hour clock"),
              Param("margin", "number", MARGIN, minimum=0, maximum=40,
                    help="Smallest gap at the left and right edges"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_tides(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))

    source = getattr(ctx, "tides", None)
    tides = source.current() if source else None
    now = ctx.now
    level = tides.height_at(now) if tides else None
    if level is None:
        c.centered("no tide data", "grey", "3x5")
        return c

    big, small = get_font("5x7"), get_font("3x5")
    margin = int(params.get("margin", MARGIN))
    hour24 = bool(params.get("hour24", False))
    count = max(1, min(4, int(params.get("count", 2) or 2)))
    day_range = tides.day_range(now.date()) if bool(params.get("day", True)) else None
    if day_range:
        # Four rows is what 32px holds at a readable pitch.
        count = min(count, 2)

    turn = tides.nearest(now)
    if turn is not None and abs(turn.when - now) <= SLACK:
        state, color = ("HIGH TIDE", RISING) if turn.high else ("LOW TIDE", FALLING)
    elif tides.rising(now):
        state, color = "RISING", RISING
    else:
        state, color = "FALLING", FALLING

    # The reading: the height large, the unit small beside it, the direction
    # underneath in the colour that carries it.
    reading = height_text(level)
    unit = tides.unit.upper()
    read_w = max(big.measure(reading) * 2 + 2 + small.measure(unit),
                 small.measure(state))

    # The table: one row per turn, label / time / height in columns, so the
    # times line up whether the hour has one digit or two. The next turns
    # are labelled in the direction colours; the day's range in grey, as the
    # reference rather than the thing to act on.
    def entry(label, event, color):
        digits, meridiem = fmt_time(event.when, hour24)
        return label, digits + meridiem, height_text(event.height), color

    rows = [entry("HIGH" if e.high else "LOW", e, RISING if e.high else FALLING)
            for e in tides.upcoming(now, count)]
    split = len(rows)
    if day_range:
        rows += [entry("MAX", day_range[0], "grey"), entry("MIN", day_range[1], "grey")]
    cols = [max((small.measure(r[i]) for r in rows), default=0) for i in range(3)]
    table_w = sum(cols) + 4 + 4 if rows else 0

    graph_w = 52 if bool(params.get("graph", True)) else 0

    # Shed rather than cross the margin: the table first, then the graph.
    # The height and its direction are the panel; they never go.
    gap = 9
    for show_graph, show_table in ((1, 1), (1, 0), (0, 0)):
        widths = [w for w in (graph_w if show_graph else 0, read_w,
                              table_w if show_table else 0) if w]
        if fits(c.width, widths, gap, margin):
            break
    names = [n for n, w in (("graph", graph_w if show_graph else 0),
                            ("read", read_w),
                            ("table", table_w if show_table else 0)) if w]
    slot = dict(zip(names, row(c.width, widths, gap, margin)))

    if "graph" in slot:
        _graph(c, slot["graph"], graph_w, tides, now)

    x = slot["read"]
    c.text(x, 4, reading, "white", big, "left", None, 2)
    c.text(x + big.measure(reading) * 2 + 2, 11, unit, "grey", small)
    c.text(x, 23, state, color, small)

    if "table" in slot:
        x = slot["table"]
        pitch = 7 if len(rows) > 2 else 9
        # A pixel more between the next turns and the day's range, so the
        # table reads as two pairs rather than four of a kind.
        extra = 1 if 0 < split < len(rows) else 0
        top = (c.height - (pitch * (len(rows) - 1) + extra + small.height)) // 2
        for index, (label, when, height, color) in enumerate(rows):
            y = top + index * pitch + (extra if index >= split else 0)
            c.text(x, y, label, color, small)
            c.text(x + cols[0] + 4, y, when, "white", small)
            # Heights right-aligned, so the decimal points stack.
            c.text(x + table_w, y, height, "grey", small, "right")
    return c
