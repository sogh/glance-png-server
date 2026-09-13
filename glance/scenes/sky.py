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
WEATHER_SEED = 0xC10D

# How much of the sky each condition takes, and how grey it makes it.
COVER = {
    "clear": (0, 0.00),
    "partly": (2, 0.22),
    "cloudy": (3, 0.55),
    "fog": (0, 0.70),
    "drizzle": (3, 0.60),
    "rain": (3, 0.70),
    "snow": (3, 0.62),
    "thunder": (3, 0.80),
}
# Cloud makes a day flat and grey, and a night *darker* -- mixing toward a
# daytime overcast after dark lit the sky up, which is exactly backwards.
OVERCAST_DAY = (118, 120, 126)
OVERCAST_NIGHT = (22, 24, 32)


def _rng(seed: int):
    state = seed

    def nxt(limit: int) -> int:
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        return state % max(1, limit)
    return nxt


def _cloud(c: Canvas, x: int, y: int, width: int, body, edge) -> int:
    """A soft blob. Returns the row its base sits on, so rain knows where to
    start falling from rather than inside it."""
    r = max(2, width // 6)
    base = y + r + 2
    c.disc(x + width // 2, y + r, r + 1, body)
    c.disc(x + r + 1, y + r + 1, r, body)
    c.disc(x + width - r - 1, y + r + 1, r, body)
    c.fill_rect(x + r, y + r, width - 2 * r, base - y - r, body)
    # A lit rim along the top, which is what stops it reading as a grey brick.
    c.hline(x + r + 1, y + 1, width - 2 * r - 2, edge)
    return base


def _clouds(c: Canvas, condition: str, night: bool) -> list[tuple[int, int, int]]:
    """Place the cloud bank. Returns (x, base, width) for each."""
    count, _ = COVER.get(condition, (2, 0.3))
    if not count:
        return []
    body = (54, 56, 66) if night else (198, 201, 208)
    edge = (76, 78, 90) if night else (238, 240, 246)
    nxt = _rng(WEATHER_SEED + len(condition))
    lane = c.width // count
    placed = []
    for i in range(count):
        width = 22 + nxt(15)
        x = i * lane + nxt(max(1, lane - width))
        y = 1 + nxt(7)
        base = _cloud(c, x, y, width, body, edge)
        placed.append((x, base, width))
    return placed


def _precipitation(c: Canvas, condition: str, banks) -> None:
    """Streaks or flakes falling from the base of each cloud to the ground,
    seeded so they hold still between fetches rather than twitching."""
    if condition not in ("rain", "drizzle", "snow", "thunder"):
        return
    snow = condition == "snow"
    colour = (222, 226, 238) if snow else (78, 138, 232)
    per_cloud = 4 if condition == "drizzle" else 7
    nxt = _rng(WEATHER_SEED ^ 0x9E37)

    for x0, base, width in banks:
        for _ in range(per_cloud):
            x = x0 + 2 + nxt(max(1, width - 4))
            start = base + 1 + nxt(3)
            if start >= HORIZON - 1:
                continue
            if snow:
                for step in (0, 4, 8):
                    yy = start + step + nxt(2)
                    if yy < HORIZON:
                        c.pixel(x, yy, colour)
            else:
                length = 3 + nxt(4)
                for k in range(length):
                    yy = start + k
                    if yy < HORIZON:
                        c.pixel(x - k // 2, yy, colour)


def _fog(c: Canvas) -> None:
    """Banded haze lying along the ground."""
    nxt = _rng(WEATHER_SEED ^ 0x5150)
    for i in range(4):
        y = HORIZON - 3 - i * 3
        if y < 2:
            break
        inset = nxt(40)
        c.fill_rect(inset, y, c.width - inset - nxt(40), 2,
                    (150, 152, 158) if i < 2 else (120, 122, 130))


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
              Param("date", "select", "sky",
                    options=["sky", "horizon", "ground", "none"],
                    help="Where the date sits, or none to leave it out"),
              Param("weather", "bool", True,
                    help="Cloud, rain and fog from the current conditions"),
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
    # An overcast sky is grey, not blue. Muting the gradient before anything
    # is drawn on it is what stops a rainy day looking like a bright one that
    # happens to have clouds pasted over it.
    condition = str(getattr(current, "condition", "clear") or "clear")
    show_weather = bool(params.get("weather", True))
    _, greyness = COVER.get(condition, (0, 0.0)) if show_weather else (0, 0.0)
    if greyness:
        overcast = OVERCAST_DAY if daytime else OVERCAST_NIGHT
        zenith = mix(zenith, overcast, min(1.0, greyness * 1.15))
        horizon = mix(horizon, overcast, min(1.0, greyness * (0.95 if daytime else 0.8)))
    _sky(c, zenith, horizon)

    if not daytime:
        # Fewer stars show through cloud.
        visible = int(params.get("stars", 26) * (1.0 - greyness))
        for x, y, brightness in _stars(c.width, visible):
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

    # Clouds go on last so they pass in front of the sun, which is the whole
    # reason an overcast day reads as overcast.
    if show_weather:
        if condition == "fog":
            _fog(c)
        else:
            banks = _clouds(c, condition, night=not daytime)
            _precipitation(c, condition, banks)

    stamp = now.strftime("%a %-d %b").upper()
    placement = str(params.get("date", "sky"))

    if placement == "sky":
        # Set into the sky like a caption on a painting: dim enough to recede,
        # and in the one corner the arc never reaches.
        c.text(3, 2, stamp, dim("white", 0.45 if daytime else 0.55), small)
    elif placement == "horizon":
        # Floating just above the horizon rather than on it: sitting on the
        # line needed a dark backing that cut the horizon in half, and at
        # night it drew straight through the moon phase label below.
        c.text(c.width // 2, HORIZON - 6, stamp,
               dim("white", 0.55 if daytime else 0.7), small, "center")

    # The caption goes on after the weather: a cloud drifting over the date
    # is atmospheric right up until you cannot read it.
    stamp = now.strftime("%a %-d %b").upper()
    placement = str(params.get("date", "sky"))
    caption = dim("white", 0.5 if daytime else 0.6)
    if greyness > 0.4 and daytime:
        caption = dim("white", 0.75)      # legible against a grey sky
    if placement == "sky":
        c.text(3, 2, stamp, caption, small)
    elif placement == "horizon":
        c.text(c.width // 2, HORIZON - 6, stamp, caption, small, "center")

    if bool(params.get("times", True)):
        # A dark backing keeps the times readable when the sun is sitting on
        # the horizon right behind them.
        rise, set_ = _fmt(sunrise), _fmt(sunset)
        c.fill_rect(0, 26, small.measure(rise) + 4, 6, (8, 10, 8))
        c.fill_rect(c.width - small.measure(set_) - 4, 26,
                    small.measure(set_) + 4, 6, (8, 10, 8))
        c.text(2, 27, rise, dim("amber", 0.9), small)
        c.text(c.width - 2, 27, set_, dim("orange", 0.9), small, "right")
    centre = []
    if placement == "ground":
        centre.append((stamp, dim("white", 0.8)))
    if bool(params.get("label", True)) and not daytime:
        centre.append((phase_at(now).short_name, dim("white", 0.6)))
    if centre:
        gap = 5
        total = sum(small.measure(t) for t, _ in centre) + gap * (len(centre) - 1)
        x = (c.width - total) // 2
        for text, colour in centre:
            c.text(x, 27, text, colour, small)
            x += small.measure(text) + gap
    return c
