"""TODO scenes driven by data/todos.json."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register


def _open(ctx: RenderContext, params: dict[str, Any]):
    if ctx.todos is None:
        return []
    items = ctx.todos.open_items(ctx.today)
    tag = params.get("tag")
    if tag:
        items = [t for t in items if t.tag.lower() == str(tag).lower()]
    return items


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    # `always: true` keeps the entry in the rotation with nothing to show, so
    # the scene can render its own "all clear" instead of the slot falling
    # through to whatever the channel's fallback is.
    if params.get("always"):
        return True
    return bool(_open(ctx, params))


def due_badge(todo, today: date) -> tuple[str, str]:
    """A short due indicator and the colour the row should take."""
    if todo.due is None:
        return "", "white"
    days = todo.days_until(today)
    if days < 0:
        return "LATE", "red"
    if days == 0:
        return "TDY", "amber"
    if days == 1:
        return "TMW", "yellow"
    if days <= 9:
        return f"{days}D", "white"
    return "", "white"


REMINDER_PARAMS = [
    Param("count", "number", 3, minimum=1, maximum=4, help="How many rows"),
    Param("style", "select", "list", options=["list", "hero"],
          help="hero draws only the most pressing one, large"),
    Param("header", "bool", True, help="Show the title bar and count"),
    Param("title", "text", "REMINDERS", help="Header text"),
    Param("accent", "color", "sky", options="@colors"),
    Param("tag", "text", None, help="Only items with this tag"),
]


@register("reminders", available=_available, description="Open reminders",
          params=REMINDER_PARAMS)
@register("todos", available=_available, description="Open items from the reminders file",
          params=REMINDER_PARAMS)
def render_todos(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    items = _open(ctx, params)
    c = ctx.canvas()
    c.clear("black")
    if not items:
        c.centered("all clear", "forest", "3x5")
        return c

    if str(params.get("style", "list")) == "hero":
        return _render_hero(c, ctx, items[0], params)
    return _render_list(c, ctx, items, params)


def _render_list(c: Canvas, ctx: RenderContext, items, params: dict[str, Any]) -> Canvas:
    show_header = bool(params.get("header", True))
    count = int(params.get("count", 3))
    accent = params.get("accent", "sky")
    small = get_font("3x5")

    top = 0
    if show_header:
        c.text(2, 0, str(params.get("title", "REMINDERS")), dim(accent, 0.9), small)
        c.text(c.width - 2, 0, str(len(items)), dim(accent, 0.6), small, "right")
        c.hline(0, 6, c.width, dim(accent, 0.25))
        top = 9

    rows = min(count, 3 if show_header else 4)
    step = 8
    for i, todo in enumerate(items[:rows]):
        y = top + i * step
        if y + 7 > c.height:
            break
        badge, color = due_badge(todo, ctx.today)
        # Priority is a 2px stripe rather than text -- it costs almost no width.
        stripe = "red" if todo.priority <= 1 else "amber" if todo.priority == 2 else dim(accent, 0.5)
        c.fill_rect(0, y + 1, 2, 5, stripe)
        badge_w = small.measure(badge) + 3 if badge else 0
        c.text(5, y, todo.text, color, "5x7", max_width=c.width - 6 - badge_w)
        if badge:
            c.text(c.width - 1, y + 1, badge, color, small, "right")
    return c


def _render_hero(c: Canvas, ctx: RenderContext, todo, params: dict[str, Any]) -> Canvas:
    """One item, as large as it will go -- for a single standing reminder."""
    badge, color = due_badge(todo, ctx.today)
    font = get_font("5x7")
    avail = c.width - 8
    scale = 2 if font.measure(todo.text) * 2 <= avail else 1
    lines = [todo.text] if scale == 2 else font.wrap(todo.text, avail)[:2]

    block = len(lines) * (font.height * scale + 2) - 2
    badge_h = 8 if badge else 0
    top = max(0, (c.height - block - badge_h) // 2)
    c.text_block(c.width // 2, top, lines, color, font, "center", leading=2, scale=scale)
    if badge:
        days = todo.days_until(ctx.today)
        label = {"LATE": "OVERDUE", "TDY": "DUE TODAY", "TMW": "DUE TOMORROW"}.get(
            badge, f"DUE IN {days} DAYS"
        )
        c.centered(label, dim(color, 0.8), "3x5", y=top + block + 3)
    return c
