"""Follower and post counts for an Instagram account."""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register


def human(value: int) -> str:
    """Panel-sized numbers. 1,284 stays exact; 12,400 becomes 12.4K.

    Exactness matters up to the point where the digits stop fitting, and a
    farm account's follower count is interesting at single-follower
    resolution in a way that 120K is not.
    """
    if value < 10_000:
        return f"{value:,}"
    if value < 1_000_000:
        trimmed = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
        return f"{trimmed}K"
    return f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    return ctx.instagram is not None and ctx.instagram.profile() is not None


@register("instagram", available=_available,
          description="Follower and post counts for an Instagram account",
          params=[
              Param("handle", "text", None,
                    help="Shown as the title; defaults to the configured account"),
              Param("accent", "color", "magenta", options="@colors"),
              Param("color", "color", "white", options="@colors"),
              Param("stale_after", "number", 21600, minimum=0,
                    help="Seconds before the age is shown as a warning"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_instagram(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small, big = get_font("3x5"), get_font("5x7")
    accent = params.get("accent", "magenta")

    source = ctx.instagram
    profile = source.profile() if source else None
    if profile is None:
        reason = (source.last_error if source and source.last_error
                  else "instagram not configured")
        c.centered("INSTAGRAM", dim(accent, 0.9), small, y=6)
        c.centered(str(reason)[:44], "dim", small, y=17, max_width=c.width - 4)
        return c

    handle = str(params.get("handle") or profile.username or "")
    c.text(2, 1, f"@{handle.upper()}", dim(accent, 0.95), small,
           max_width=c.width - 40)

    # Age lives top-right, and only speaks up once the number is old enough to
    # doubt. A silent panel means the figure is current.
    stale_after = float(params.get("stale_after", 21600))
    age = profile.age_seconds()
    if stale_after and age > stale_after:
        c.text(c.width - 2, 1, profile.age_text(), "amber", small, "right")

    # Two columns: followers on the left, posts on the right.
    half = c.width // 2
    columns = ((profile.followers, "FOLLOWERS"), (profile.posts, "POSTS"))
    for index, (value, label) in enumerate(columns):
        centre = half // 2 + index * half
        text = human(value)
        scale = 2 if big.measure(text) * 2 <= half - 8 else 1
        c.text(centre, 9 if scale == 2 else 12, text,
               params.get("color", "white"), big, "center", half - 6, scale)
        c.text(centre, 25, label, dim(accent, 0.8), small, "center", half - 4)

    c.vline(half, 4, c.height - 8, dim(accent, 0.3))
    return c
