"""Holiday scenes -- either your own artwork or a generated title card."""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from ..sources.holidays import active_holidays
from .base import Param, RenderContext, register
from .static_image import load_image, resolve_path


def _active(ctx: RenderContext, params: dict[str, Any]):
    hits = active_holidays(ctx.holidays, ctx.today)
    if params.get("name"):
        wanted = str(params["name"]).lower()
        hits = [h for h in hits if wanted in (h[0].slug, h[0].name.lower())]
    return hits


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    return bool(_active(ctx, params))


def countdown_label(days: int) -> str:
    if days == 0:
        return "TODAY"
    if days == 1:
        return "TOMORROW"
    if days > 1:
        return f"IN {days} DAYS"
    if days == -1:
        return "YESTERDAY"
    return f"{abs(days)} DAYS AGO"


@register("holiday", available=_available, description="The currently active holiday",
          params=[
              Param("name", "text", None, help="Pin to one holiday by name or slug"),
              Param("index", "number", 0, minimum=0,
                    help="Which one, when several are active at once"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_holiday(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    hits = _active(ctx, params)
    c = ctx.canvas()
    if not hits:
        c.clear("black")
        c.centered("no holiday", "dim", "3x5")
        return c

    index = int(params.get("index", 0)) % len(hits)
    holiday, days = hits[index]

    # Bespoke artwork wins over the generated card whenever it exists.
    if holiday.image:
        path = resolve_path(ctx, str(holiday.image))
        if path is not None:
            c.clear("black")
            c.fit(load_image(path))
            if holiday.countdown and days > 0:
                label = countdown_label(days)
                font = get_font("3x5")
                w = font.measure(label)
                c.fill_rect(c.width - w - 5, c.height - 7, w + 5, 7, "black")
                c.text(c.width - 3, c.height - 6, label, holiday.accent, font, "right")
            return c

    # Generated title card: accent rules top and bottom, name, then a subtitle
    # or a countdown.
    c.clear(params.get("background", "black"))
    c.fill_rect(0, 0, c.width, 2, holiday.accent)
    c.fill_rect(0, c.height - 2, c.width, 2, holiday.accent)
    c.fill_rect(0, 2, c.width, 1, dim(holiday.accent, 0.35))
    c.fill_rect(0, c.height - 3, c.width, 1, dim(holiday.accent, 0.35))

    sub = holiday.subtitle or (countdown_label(days) if holiday.countdown or days != 0 else "")
    title_font = get_font("5x7")
    scale = 2 if title_font.measure(holiday.name) * 2 <= c.width - 12 else 1

    if sub:
        block_h = title_font.height * scale + 4 + get_font("3x5").height
        top = (c.height - block_h) // 2
        c.centered(holiday.name, holiday.color, title_font, y=top, max_width=c.width - 8, scale=scale)
        c.centered(sub, dim(holiday.accent, 0.9), "3x5",
                   y=top + title_font.height * scale + 4, max_width=c.width - 8)
    else:
        c.centered(holiday.name, holiday.color, title_font, max_width=c.width - 8, scale=scale)
    return c
