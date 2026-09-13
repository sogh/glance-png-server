"""Where something last happened.

A list of motion sensors mostly reads "OFF, OFF, OFF, OFF", which tells you
nothing. What is worth knowing is which zone saw movement and how long ago, so
this ranks them by recency instead of listing them by name.
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register

STRIP = (" MOTION", " SENSOR", " CAMERA")


def tidy(name: str) -> str:
    """Trim the words every zone shares, which waste a narrow panel."""
    label = " ".join(str(name or "").split()).upper()
    for suffix in STRIP:
        if label.endswith(suffix):
            label = label[: -len(suffix)]
    return label.strip()


def _zones(ctx: RenderContext, params: dict[str, Any]):
    source = getattr(ctx, "homeassistant", None)
    if source is None or not source.configured:
        return []
    spec = str(params.get("entities", "") or "")
    if spec:
        return [e for e, _, _ in source.pick(spec) if e is not None and e.available]
    return source.of_class(str(params.get("device_class", "motion")))


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    return bool(params.get("always")) or bool(_zones(ctx, params))


@register("activity", available=_available,
          description="Which zone saw movement, and how long ago",
          params=[
              Param("entities", "text", None,
                    help="Leave blank to use every motion sensor you have"),
              Param("device_class", "text", "motion",
                    help="Which class to gather when entities is blank"),
              Param("count", "number", 4, minimum=1, maximum=4),
              Param("title", "text", None, help="Header line"),
              Param("accent", "color", "teal", options="@colors"),
              Param("alert", "color", "amber", options="@colors",
                    help="Colour for a zone that is active right now"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_activity(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small, big = get_font("3x5"), get_font("5x7")
    accent = params.get("accent", "teal")

    zones = _zones(ctx, params)
    if not zones:
        source = getattr(ctx, "homeassistant", None)
        reason = (source.last_error if source and source.last_error
                  else "no motion sensors found")
        c.centered("ACTIVITY", dim(accent, 0.9), small, y=6)
        c.centered(str(reason)[:44], "dim", small, y=17, max_width=c.width - 4)
        return c

    title = params.get("title")
    top, rows = 0, int(params.get("count", 4))
    if title:
        c.text(2, 0, str(title).upper(), dim(accent, 0.9), small)
        c.hline(0, 6, c.width, dim(accent, 0.25))
        top, rows = 9, min(rows, 3)

    step = 8
    for index, zone in enumerate(zones[:rows]):
        y = top + index * step
        if y + 7 > c.height:
            break
        active = zone.state.lower() in ("on", "detected")
        stamp = "NOW" if active else zone.ago(ctx.now)
        colour = params.get("alert", "amber") if active else "white"

        stamp_w = big.measure(stamp)
        c.text(2, y, tidy(zone.name), dim(accent, 0.95) if not active else colour,
               small, max_width=c.width - stamp_w - 8)
        c.text(c.width - 2, max(0, y - 1), stamp, colour, big, "right")
    return c
