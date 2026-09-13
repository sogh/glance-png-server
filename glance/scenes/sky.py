"""The sun and moon crossing the sky.

A 192x32 strip is almost exactly the shape of a horizon, so the day is drawn
as an arc across it: the sun rises on the left, sets on the right, and after
dark the moon takes the same path with its real phase carved out of it.

Everything is computed — sunrise and sunset come from the coordinates already
configured for weather, and the moon phase is arithmetic. Nothing to set up.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..moon import lit as moon_lit
from ..moon import phase_at
from ..palette import RGB, dim, mix, parse
from .base import Param, RenderContext, register

HORIZON = 26
PEAK = 5                       # how close to the top the arc reaches at noon

# zenith, horizon
NIGHT = ((0, 0, 10), (12, 10, 34))
TWILIGHT = ((24, 12, 52), (210, 70, 8))
DAY = ((10, 48, 122), (120, 175, 232))

# Fixed so the stars do not reshuffle on every fetch.
STAR_SEED = 0x5EED


def _stars(width: int, count: int) -> list[tuple[int, int, int]]:
    """Deterministic star field: x, y, brightness."""
    out, state = [], STAR_SEED
    for _ in range(count):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        x = state % width
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        y = state % (HORIZON - 2)
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((x, y, 60 + state % 150))
    return out


def _sky(c: Canvas, zenith: RGB, horizon: RGB) -> None:
    for y in range(HORIZON):
        c.hline(0, y, c.width, mix(zenith, horizon, y / max(1, HORIZON - 1)))


def _arc_y(t: float) -> float:
    """Height of the arc at fraction `t` of the traverse."""
    return HORIZON - 2 - (HORIZON - 2 - PEAK) * math.sin(math.pi * max(0.0, min(1.0, t)))


def _draw_sun(c: Canvas, x: int, y: int, low: bool) -> None:
    colour = "orange" if low else "amber"
    c.disc(x, y, 3, colour)
    if low:
        # No rays near the horizon: a setting sun does not have them, and they
        # would reach down into the row the times are written on.
        return
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        for step in (5, 6):
            c.pixel(x + dx * step, y + dy * step, dim(colour, 0.85))


def _draw_moon(c: Canvas, x: int, y: int, phase: float, radius: int = 4) -> None:
    """The disc with its real terminator. A sliver of earthshine keeps a thin
    crescent from vanishing into the sky entirely."""
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            if moon_lit(dx, dy, radius, phase):
                c.pixel(x + dx, y + dy, (235, 235, 225))
            else:
                c.pixel(x + dx, y + dy, (26, 26, 40))


def _fmt(when: datetime | None) -> str:
    if when is None:
        return "--"
    hour = when.hour % 12 or 12
    return f"{hour}:{when.minute:02d}{'A' if when.hour < 12 else 'P'}"


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    source = getattr(ctx, "weather", None)
    if source is None or not source.configured:
        return False
    current = source.current()
    return bool(current and current.sunrise and current.sunset)


@register("sky", available=_available,
          description="Sun and moon crossing the sky, with the real phase",
          params=[
              Param("times", "bool", True, help="Sunrise and sunset in the corners"),
              Param("label", "bool", True, help="Name the moon phase at night"),
              Param("stars", "number", 26, minimum=0, maximum=80),
          ])
def render_sky(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    small = get_font("3x5")
    now = ctx.now

    source = getattr(ctx, "weather", None)
    current = source.current() if source else None
    sunrise = getattr(current, "sunrise", None)
    sunset = getattr(current, "sunset", None)

    # The fetched times are dated to whenever the forecast was pulled, which
    # stops matching the moment the clock passes midnight — and then every
    # frame decides it is night. Sunrise moves by a minute or two a day, so
    # re-dating the time of day onto today is both robust and accurate enough.
    if sunrise and sunset:
        sunrise = datetime.combine(ctx.today, sunrise.timetz())
        sunset = datetime.combine(ctx.today, sunset.timetz())

    if not (sunrise and sunset):
        c.clear("black")
        c.centered("set coordinates for sunrise times", "dim", small,
                   max_width=c.width - 4)
        return c

    daytime = sunrise <= now <= sunset
    if daytime:
        span = (sunset - sunrise).total_seconds()
        t = (now - sunrise).total_seconds() / max(1.0, span)
    else:
        # Night runs from sunset to the next sunrise; before dawn the previous
        # evening's sunset is the one that matters.
        if now > sunset:
            start, end = sunset, sunrise + timedelta(days=1)
        else:
            start, end = sunset - timedelta(days=1), sunrise
        t = (now - start).total_seconds() / max(1.0, (end - start).total_seconds())
    t = max(0.0, min(1.0, t))

    # Colour follows how near the horizon the body is: the arc height doubles
    # as an altitude proxy, which is what makes dawn and dusk warm.
    altitude = math.sin(math.pi * t)
    if daytime:
        warmth = max(0.0, 1.0 - altitude / 0.28)
        zenith = mix(DAY[0], TWILIGHT[0], warmth)
        horizon = mix(DAY[1], TWILIGHT[1], warmth)
    else:
        edge = max(0.0, 1.0 - altitude / 0.18)
        zenith = mix(NIGHT[0], TWILIGHT[0], edge * 0.7)
        horizon = mix(NIGHT[1], TWILIGHT[1], edge * 0.85)
    _sky(c, zenith, horizon)

    if not daytime:
        for x, y, brightness in _stars(c.width, int(params.get("stars", 26))):
            shade = int(brightness * (0.35 + 0.65 * min(1.0, altitude * 2)))
            if shade > 20:
                c.pixel(x, y, (shade, shade, min(255, shade + 20)))

    # Ground, then the body on its arc.
    c.fill_rect(0, HORIZON, c.width, c.height - HORIZON, (8, 10, 8))
    c.hline(0, HORIZON, c.width, dim(horizon, 0.55))

    x = int(4 + t * (c.width - 8))
    y = int(round(_arc_y(t)))
    if daytime:
        _draw_sun(c, x, y, low=altitude < 0.25)
    else:
        _draw_moon(c, x, y, phase_at(now).phase)

    if bool(params.get("times", True)):
        # A dark backing keeps the times readable when the sun is sitting on
        # the horizon right behind them.
        rise, set_ = _fmt(sunrise), _fmt(sunset)
        c.fill_rect(0, 26, small.measure(rise) + 4, 6, (8, 10, 8))
        c.fill_rect(c.width - small.measure(set_) - 4, 26,
                    small.measure(set_) + 4, 6, (8, 10, 8))
        c.text(2, 27, rise, dim("amber", 0.9), small)
        c.text(c.width - 2, 27, set_, dim("orange", 0.9), small, "right")
    if bool(params.get("label", True)) and not daytime:
        c.text(c.width // 2, 27, phase_at(now).short_name, dim("white", 0.7),
               small, "center", 80)
    return c
