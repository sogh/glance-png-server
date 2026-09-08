"""Small utility scenes: a clock, arbitrary configured text, and a blank."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import RenderContext, register


@register("clock", description="Time and date")
def render_clock(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    hour24 = bool(params.get("hour24", False))
    color = params.get("color", "white")

    if hour24:
        stamp, meridiem = ctx.now.strftime("%H:%M"), ""
    else:
        stamp = f"{ctx.now.hour % 12 or 12}:{ctx.now.minute:02d}"
        meridiem = "AM" if ctx.now.hour < 12 else "PM"

    show_date = bool(params.get("date", True))
    top = 4 if show_date else 9

    # Monospaced digits so the layout does not jitter as the minutes tick over.
    # The meridiem sits beside the time, baseline-aligned, rather than being
    # appended to the date line where it reads as part of the date.
    mono, small = get_font("5x7mono"), get_font("3x5")
    time_w = mono.measure(stamp) * 2
    gap = 4
    total = time_w + (gap + small.measure(meridiem) if meridiem else 0)
    x = (c.width - total) // 2

    c.text(x, top, stamp, color, mono, scale=2)
    if meridiem:
        c.text(x + time_w + gap, top + mono.height * 2 - small.height,
               meridiem, dim(color, 0.7), small)
    if show_date:
        line = ctx.now.strftime("%a %d %b").upper().replace(" 0", " ")
        c.centered(line, dim(params.get("accent", "sky"), 0.9), "3x5", y=23)
    return c


@register("text", description="Fixed text from the channel config")
def render_text(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    body = str(params.get("text", ""))
    if not body:
        c.centered("(no text)", "dim", "3x5")
        return c

    color = params.get("color", "white")
    sub = params.get("sub")
    font = get_font(str(params.get("font", "5x7")))
    avail = c.width - 6

    scale = int(params.get("scale", 0)) or (2 if font.measure(body) * 2 <= avail else 1)
    lines = [body] if font.measure(body) * scale <= avail else font.wrap(body, avail // scale)[:2]

    block = len(lines) * (font.height * scale + 2) - 2
    sub_h = get_font("3x5").height + 4 if sub else 0
    top = max(0, (c.height - block - sub_h) // 2)
    c.text_block(c.width // 2, top, lines, color, font, "center", leading=2, scale=scale)
    if sub:
        c.centered(str(sub), params.get("sub_color", dim(color, 0.6)), "3x5",
                   y=top + block + 4)
    return c


@register("blank", description="An intentionally dark panel")
def render_blank(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    return c


@register("countdown", description="Days remaining until a target date")
def render_countdown(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    target_raw = params.get("date")
    if not target_raw:
        c.centered("no date set", "red", "3x5")
        return c

    target = date.fromisoformat(str(target_raw)[:10])
    days = (target - ctx.today).days
    label = str(params.get("label", "")).upper()
    color = params.get("color", "amber")

    if days == 0:
        c.centered(label or "TODAY", color, "5x7", y=12, scale=2)
        return c

    number = str(abs(days))
    word = "DAY" if abs(days) == 1 else "DAYS"
    tail = word if days > 0 else f"{word} AGO"

    c.centered(number, color, "5x7mono", y=3, scale=3 if len(number) <= 3 else 2)
    if label:
        c.centered(f"{tail} TO {label}", dim(color, 0.8), "3x5", y=26)
    else:
        c.centered(tail, dim(color, 0.8), "3x5", y=26)
    return c
