"""Scrolling text, emitted as an animated PNG.

Whether the panel animates it depends on the device's decoder -- see
glance/animation.py. If it does not, it shows the first frame, so nothing is
lost by trying.
"""

from __future__ import annotations

from typing import Any

from ..animation import Frames, marquee_frames
from ..canvas import Canvas
from .base import RenderContext, register


@register("marquee", description="Scrolling text (animated PNG)")
def render_marquee(ctx: RenderContext, params: dict[str, Any]) -> Frames | Canvas:
    text = str(params.get("text", "")).strip()
    if not text:
        c = ctx.canvas()
        c.clear("black")
        c.centered("(no text)", "dim", "3x5")
        return c

    return marquee_frames(
        width=ctx.settings.width,
        text=text,
        color=params.get("color", "amber"),
        font=str(params.get("font", "5x7")),
        step=int(params.get("step", 2)),
        duration=int(params.get("duration", 80)),
        scale=int(params.get("scale", 1)),
        background=params.get("background", "black"),
    )
