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

    detail_x = temp_x + big.measure(temp) * scale + 7
    room = c.width - detail_x - 2
    if room < 26:
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

    x = detail_x
    for index, (text, color) in enumerate(segments):
        gap = 0 if index and segments[index - 1][0] == "AQI" else 4
        width = small.measure(text)
        if x + gap + width > c.width - 1:
            break
        x += gap if index else 0
        c.text(x, 22, text, color, small)
        x += width
    return c
