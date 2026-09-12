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
              Param("background", "color", "black", options="@colors"),
          ])
def render_weather(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))

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

    # Icon, then the temperature, then the detail column.
    draw_icon(c, current.condition, 2, (c.height - icon_size) // 2,
              icon_size, night=not current.is_day)

    temp = f"{current.temperature:.0f}°"
    scale = 2 if big.measure(temp) * 2 <= 46 else 1
    temp_x = icon_size + 7
    c.text(temp_x, (c.height - big.height * scale) // 2, temp,
           _temp_color(current.temperature, params.get("color", "white")),
           big, "left", None, scale)

    # The forecast claims its columns from the right edge first; the detail
    # text then gets whatever is left, and drops lines that no longer fit.
    days = int(params.get("forecast", 3))
    shown = current.forecast[:max(0, days)]
    forecast_w = len(shown) * FORECAST_COLUMN
    if shown:
        _draw_forecast(c, shown, c.width - forecast_w, small, params)

    detail_x = temp_x + big.measure(temp) * scale + 7
    room = c.width - detail_x - 2 - (forecast_w + 4 if shown else 0)
    if room < 20:
        return c

    c.text(detail_x, 4, current.label, dim(params.get("accent", "amber"), 0.95),
           small, max_width=room)
    c.text(detail_x, 13, f"H {current.high:.0f}  L {current.low:.0f}",
           "grey", small, max_width=room)

    # Third line packs in whatever fits, left to right, dropping anything that
    # would overflow rather than truncating it into nonsense.
    segments: list[tuple[str, Any]] = []
    if bool(params.get("precip", True)) and current.precip_text:
        segments.append((current.precip_text, "sky"))
    if bool(params.get("aqi", True)) and current.aqi is not None:
        # The number carries the colour: an AQI means nothing unless you
        # already know the bands, and the colour is the band.
        segments.append(("AQI", dim("grey", 0.9)))
        segments.append((f"{current.aqi:.0f}", current.aqi_band[1]))
    if (bool(params.get("feels", False))
            and abs(current.feels_like - current.temperature) >= 2):
        segments.append((f"FEELS {current.feels_like:.0f}", dim("grey", 0.8)))

    limit = detail_x + room
    x = detail_x
    for index, (text, color) in enumerate(segments):
        gap = 0 if index and segments[index - 1][0] == "AQI" else 4
        width = small.measure(text)
        if x + gap + width > limit:
            break
        x += gap if index else 0
        c.text(x, 22, text, color, small)
        x += width
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
        draw_icon(c, day.condition, x + (FORECAST_COLUMN - 12) // 2, 8, 12)
        c.text(mid, 22, f"{day.high:.0f}", _temp_color(day.high, "white"),
               small, "center", FORECAST_COLUMN - 1)

    # A hairline keeps the forecast from reading as part of today's numbers.
    if days:
        c.vline(x0 - 3, 3, c.height - 6, dim("grey", 0.35))
