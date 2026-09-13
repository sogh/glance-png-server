"""Home Assistant entity states."""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register


def _source(ctx: RenderContext):
    return getattr(ctx, "homeassistant", None)


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    source = _source(ctx)
    if source is None or not source.configured:
        return False
    return any(e for e, _, _ in source.pick(params.get("entities", "")))


def _label_for(entity, entity_id: str, override: str) -> str:
    if override:
        return override.upper()
    if entity is not None and entity.name:
        return entity.name.upper()
    # Fall back to the bare object id, which is at least recognisable.
    return entity_id.split(".", 1)[-1].replace("_", " ").upper()


@register("entities", available=_available,
          description="Home Assistant entity states",
          params=[
              Param("entities", "text", "",
                    help="entity_id list, comma separated. "
                         "Add =Label to shorten a long name for the panel."),
              Param("layout", "select", "columns", options=["columns", "rows"],
                    help="columns: up to 3 side by side. rows: up to 4 stacked."),
              Param("title", "text", None, help="Header line, rows layout only"),
              Param("accent", "color", "teal", options="@colors"),
              Param("alert", "color", "red", options="@colors",
                    help="Colour for a low battery or an open door"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_entities(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small, big = get_font("3x5"), get_font("5x7")
    accent = params.get("accent", "teal")

    source = _source(ctx)
    if source is None or not source.configured:
        c.centered("HOME ASSISTANT", dim(accent, 0.9), small, y=6)
        reason = (source.last_error if source and source.last_error
                  else "url or token not set")
        c.centered(str(reason)[:44], "dim", small, y=17, max_width=c.width - 4)
        return c

    picked = source.pick(params.get("entities", ""))
    if not picked:
        c.centered("no entities configured", "dim", small, max_width=c.width - 4)
        return c

    if str(params.get("layout", "columns")) == "rows":
        return _rows(c, picked, params, small, big, accent)
    return _columns(c, picked, params, small, big, accent)


def _value_colour(entity, params: dict[str, Any]) -> str:
    if entity is None or not entity.available:
        return dim("grey", 0.7)
    if entity.alerting:
        return params.get("alert", "red")
    return "white"


def _columns(c, picked, params, small, big, accent):
    """Up to three side by side: name above, value below."""
    picked = picked[:3]
    width = c.width // max(1, len(picked))

    for index, (entity, entity_id, override) in enumerate(picked):
        x = index * width
        mid = x + width // 2
        if index:
            c.vline(x - 1, 3, c.height - 6, dim(accent, 0.25))

        c.text(mid, 2, _label_for(entity, entity_id, override),
               dim(accent, 0.95), small, "center", width - 4)

        text = entity.display() if entity is not None else "--"
        scale = 2 if big.measure(text) * 2 <= width - 6 else 1
        c.text(mid, 12 if scale == 2 else 15, text,
               _value_colour(entity, params), big, "center", width - 4, scale)
    return c


def _rows(c, picked, params, small, big, accent):
    """Up to four stacked: name left, value right."""
    title = params.get("title")
    top = 0
    if title:
        c.text(2, 0, str(title).upper(), dim(accent, 0.9), small)
        c.hline(0, 6, c.width, dim(accent, 0.25))
        top = 9

    rows = picked[:3 if title else 4]
    step = 8
    for index, (entity, entity_id, override) in enumerate(rows):
        y = top + index * step
        if y + 7 > c.height:
            break
        text = entity.display() if entity is not None else "--"
        value_w = big.measure(text)
        c.text(2, y, _label_for(entity, entity_id, override),
               dim(accent, 0.9), small, max_width=c.width - value_w - 8)
        # The value font is two rows taller than the label, so it is nudged up
        # to sit level -- but never above the panel, which clipped the first
        # row when there was no title above it.
        c.text(c.width - 2, max(0, y - 1), text, _value_colour(entity, params),
               big, "right")
    return c
