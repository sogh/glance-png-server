"""Scrolling text, emitted as an animated PNG.

Whether the panel animates it depends on the device's decoder -- see
glance/animation.py. If it does not, it shows the first frame, so nothing is
lost by trying.
"""

from __future__ import annotations

from typing import Any

from ..animation import Frames, marquee_frames
from ..canvas import Canvas
from .base import Param, RenderContext, register


@register("marquee", description="Scrolling text (animated PNG; this panel shows frame 0)",
          params=[
              Param("text", "text", "", help="What scrolls"),
              Param("color", "color", "amber", options="@colors"),
              Param("font", "select", "5x7", options="@fonts"),
              Param("step", "number", 2, minimum=1, maximum=8,
                    help="Pixels per frame"),
              Param("duration", "number", 80, minimum=20, maximum=1000),
              Param("scale", "number", 1, minimum=1, maximum=4),
              Param("background", "color", "black", options="@colors"),
          ])
def render_marquee(ctx: RenderContext, params: dict[str, Any]) -> Frames | Canvas:
    text = str(params.get("text", "")).strip()
    if not text:
        c = ctx.canvas()
        c.clear("black")
        c.centered("(no text)", "dim", "3x5")
        return c

    return marquee_frames(
        width=ctx.width,
        text=text,
        color=params.get("color", "amber"),
        font=str(params.get("font", "5x7")),
        step=int(params.get("step", 2)),
        duration=int(params.get("duration", 80)),
        scale=int(params.get("scale", 1)),
        background=params.get("background", "black"),
    )
