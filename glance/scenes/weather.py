"""Current conditions."""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from ..weathericons import draw as draw_icon
from .base import Param, RenderContext, register

WARM = 75
COLD = 45
FORECAST_COLUMN = 21        # per day: a label, a small icon and a high


def _temp_color(value: float, default: str = "white") -> str:
    """Warm colours for warm days. Makes the number readable at a glance from
    across a room, before you have read the digits."""
    if value >= WARM:
        return "orange"
    if value <= COLD:
        return "sky"
    return default


def _high_low(high: float, low: float, room: int, font) -> str:
    """The widest high/low that fits `room`, or "" if even the high will not.

    It gives up the spacing first, then the low itself. Truncation is not one
    of the options: an ellipsis where a temperature should be says less than
    no low at all, and the worst case -- a three-digit high beside a negative
    low, drawn as "H 100  L -.." -- is a real winter reading, not a contrived
    one.
    """
    for line in (f"H {high:.0f}  L {low:.0f}", f"H {high:.0f} L {low:.0f}",
                 f"{high:.0f}/{low:.0f}", f"H {high:.0f}"):
        if font.measure(line) <= room:
            return line
    return ""


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    return ctx.weather is not None and ctx.weather.current() is not None


@register("weather", available=_available, description="Current conditions",
          params=[
              Param("color", "color", "white", options="@colors",
                    help="Only used for mild temperatures; hot and cold pick their own"),
              Param("accent", "color", "amber", options="@colors"),
              Param("precip", "bool", True,
                    help="Chance of rain today, or the amount if it is falling now"),
              Param("aqi", "bool", True,
                    help="US AQI, coloured by band: green good, red unhealthy"),
              Param("forecast", "number", 3, minimum=0, maximum=3,
                    help="Days of forecast on the right; 0 for none"),
              Param("feels", "bool", False, help="Show 'feels like' when it differs"),
              Param("margin", "number", 8, minimum=0, maximum=40,
                    help="Blank kept at each edge, so the pane separates from "
                         "its neighbours as the device pans past"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_weather(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    background = params.get("background", "black")
    c.clear(background)

    source = ctx.weather
    current = source.current() if source else None
    if current is None:
        message = ("set sources.weather latitude/longitude"
                   if source is None or not source.configured
                   else "weather unavailable")
        c.centered(message, "dim", "3x5", max_width=c.width - 4)
        return c

    small = get_font("3x5")
    big = get_font("5x7")
    icon_size = min(22, c.height - 4)

    # Everything hangs off these two, rather than off the panel edges: the
    # device pans straight from one app into the next, and a pane inked end
    # to end has nothing to say where it stops and its neighbour starts.
    margin = max(0, int(params.get("margin", 8) or 0))
    left, right = margin, c.width - margin

    # Icon, then the temperature, then the detail column.
    draw_icon(c, current.condition, left, (c.height - icon_size) // 2,
              icon_size, night=not current.is_day, background=background)

    temp = f"{current.temperature:.0f}°"
    temp_x = left + icon_size + 5
    # The budget comes from what is actually left, not from a constant. It
    # used to be a flat 46, which quietly encoded the old edge-to-edge
    # geometry -- give the pane margins and a 64px panel pushed the
    # temperature off its own right-hand side.
    scale = 2 if big.measure(temp) * 2 <= min(46, right - temp_x) else 1
    c.text(temp_x, (c.height - big.height * scale) // 2, temp,
           _temp_color(current.temperature, params.get("color", "white")),
           big, "left", None, scale)

    # The forecast claims its columns from the right edge first; the detail
    # text then gets whatever is left, and drops lines that no longer fit.
    days = int(params.get("forecast", 3))
    shown = current.forecast[:max(0, days)]
    # Drop columns that will not fit rather than draw them anyway. Three
    # columns is 63px, so on a single 64px module the block was being placed
    # at a negative x and bleeding back across the icon -- visible only once
    # the pane gained margins and the number went properly negative.
    temp_end = temp_x + big.measure(temp) * scale
    while shown and right - len(shown) * FORECAST_COLUMN < temp_end + 6:
        shown = shown[:-1]
    forecast_w = len(shown) * FORECAST_COLUMN
    if shown:
        _draw_forecast(c, shown, right - forecast_w, small, params)

    detail_x = temp_x + big.measure(temp) * scale + 7
    room = right - detail_x - (forecast_w + 4 if shown else 0)
    if room < 20:
        return c

    c.text(detail_x, 4, current.label, dim(params.get("accent", "amber"), 0.95),
           small, max_width=room)
    high_low = _high_low(current.high, current.low, room, small)
    if high_low:
        c.text(detail_x, 13, high_low, "grey", small)

    # Third line packs in whatever fits, left to right, dropping any reading
    # that would overflow rather than truncating it into nonsense. A reading
    # goes down whole or not at all, which is why each is a list: "AQI" and
    # its number are one reading, not two. Placed separately, a tight line
    # would take the word and drop the number -- leaving a bare grey "AQI"
    # standing for nothing, with the colour that carries the band gone.
    readings: list[list[tuple[str, Any]]] = []
    if bool(params.get("precip", True)) and current.precip_text:
        readings.append([(current.precip_text, "sky")])
    if bool(params.get("aqi", True)) and current.aqi is not None:
        # The number carries the colour: an AQI means nothing unless you
        # already know the bands, and the colour is the band.
        readings.append([("AQI", dim("grey", 0.9)),
                         (f"{current.aqi:.0f}", current.aqi_band[1])])
    if (bool(params.get("feels", False))
            and abs(current.feels_like - current.temperature) >= 2):
        readings.append([(f"FEELS {current.feels_like:.0f}", dim("grey", 0.8))])

    limit = detail_x + room
    x = detail_x
    for reading in readings:
        # Words within a reading get a hair of space; separate readings get
        # the full gap, and nothing is owed before the first one.
        width = sum(small.measure(t) for t, _ in reading) + 2 * (len(reading) - 1)
        lead = 4 if x > detail_x else 0
        if x + lead + width > limit:
            continue          # a shorter reading further along may still fit
        x += lead
        for index, (text, color) in enumerate(reading):
            x += 2 if index else 0
            c.text(x, 22, text, color, small)
            x += small.measure(text)
    return c


def _draw_forecast(c: Canvas, days, x0: int, small, params: dict[str, Any]) -> None:
    """A column per day: weekday, a small icon, and the high.

    Only the high is shown. Two temperatures per 21px column is more than the
    space can carry legibly, and the low is the one you can do without.
    """
    from datetime import date

    for index, day in enumerate(days):
        x = x0 + index * FORECAST_COLUMN
        mid = x + FORECAST_COLUMN // 2

        try:
            label = date.fromisoformat(day.date).strftime("%a").upper()
        except ValueError:
            label = "?"
        c.text(mid, 1, label, dim("grey", 0.9), small, "center", FORECAST_COLUMN - 1)
        draw_icon(c, day.condition, x + (FORECAST_COLUMN - 12) // 2, 8, 12,
                  background=params.get("background", "black"))
        c.text(mid, 22, f"{day.high:.0f}", _temp_color(day.high, "white"),
               small, "center", FORECAST_COLUMN - 1)

    # A hairline keeps the forecast from reading as part of today's numbers.
    if days:
        c.vline(x0 - 3, 3, c.height - 6, dim("grey", 0.35))
