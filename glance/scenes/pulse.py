"""Text that breathes between white and a colour.

Written as an animated PNG. If the panel does not decode APNG it shows frame
zero, which is the all-white state -- still perfectly readable.

    /s/pulse.png?items=ADA:yellow,GRACE:blue
"""

from __future__ import annotations

import math
from typing import Any

from ..animation import Frames
from ..canvas import Canvas
from ..fonts import get_font
from ..palette import mix
from .base import RenderContext, register

DEFAULT_ITEMS = "ADA:yellow,GRACE:blue"


def parse_items(raw: str) -> list[tuple[str, str]]:
    """`NAME:colour,NAME:colour` -> [(name, colour), ...]

    A comma-and-colon string rather than nested YAML so the same value works
    from a channel config, the editor's params box, and a query string.
    """
    out: list[tuple[str, str]] = []
    for chunk in str(raw).split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        text, _, color = chunk.partition(":")
        out.append((text.strip(), (color.strip() or "white")))
    return out


def _fit_scale(font, texts: list[str], available: int, stacked: bool, height: int) -> int:
    """Largest whole-pixel scale that still fits. Whole numbers only -- a
    fractional scale would put glyph edges between pixels."""
    for scale in (4, 3, 2, 1):
        if stacked:
            widest = max(font.measure(t) * scale for t in texts)
            tall = len(texts) * (font.height * scale + 2) - 2
            if widest <= available and tall <= height:
                return scale
        else:
            total = sum(font.measure(t) * scale for t in texts) + 8 * (len(texts) - 1)
            if total <= available and font.height * scale <= height:
                return scale
    return 1


def _draw(c: Canvas, text: str, colour: Any, x: int, y: int, font, scale: int,
          align: str, gradient_from: str | None) -> None:
    if gradient_from is None:
        c.text(x, y, text, colour, font, align, None, scale)
    else:
        c.text_gradient(x, y, text, gradient_from, colour, font, align, scale)


@register("pulse", description="Names in a colour, over time or across the letters")
def render_pulse(ctx: RenderContext, params: dict[str, Any]) -> Frames | Canvas:
    items = parse_items(params.get("items", DEFAULT_ITEMS))
    if not items:
        c = ctx.canvas()
        c.clear("black")
        c.centered("(no items)", "dim", "3x5")
        return c

    font = get_font(str(params.get("font", "5x7")))
    frame_count = max(2, int(params.get("frames", 30)))
    duration = int(params.get("duration", 70))
    background = params.get("background", "black")
    # Stagger offsets each item in the cycle so they take turns being bright.
    stagger = float(params.get("stagger", 0.0))
    # How far toward white the dim end goes; 0 is fully white at the trough.
    floor = max(0.0, min(1.0, float(params.get("floor", 0.0))))

    texts = [t for t, _ in items]
    stacked = str(params.get("layout", "column" if len(items) > 1 else "row")) == "column"
    fits = _fit_scale(font, texts, ctx.width - 6, stacked, ctx.height)
    requested = int(params.get("scale", 0))
    # Clamp rather than obey: a scale that does not fit clips the glyphs, and
    # a half-drawn name is worse than a smaller one.
    scale = min(requested, fits) if requested > 0 else fits

    # This device does not decode APNG -- it renders frame zero and stops. So
    # the default is a gradient across the letters rather than across time:
    # the same white-to-colour transition, in one frame, visible on hardware
    # that will never animate. `mode: pulse` restores the animation for a
    # panel that can show it.
    mode = str(params.get("mode", "gradient"))
    if mode == "gradient":
        c = ctx.canvas()
        c.clear(background)
        _layout(c, items, texts, font, scale, stacked, gradient=True,
                gradient_from=params.get("from", "white"))
        return c

    canvases: list[Canvas] = []
    for frame in range(frame_count):
        c = ctx.canvas()
        c.clear(background)

        for index, (text, color) in enumerate(items):
            # A raised cosine: starts at white, eases to full colour, eases
            # back. Ending where it started is what makes the loop seamless.
            phase = frame / frame_count + stagger * index
            t = (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0
            shade = mix("white", color, floor + (1.0 - floor) * t)

            _place(c, texts, index, text, shade, font, scale, stacked, None)

        canvases.append(c)

    return Frames(canvases=canvases, duration=duration)


def _place(c: Canvas, texts: list[str], index: int, text: str, colour: Any,
           font, scale: int, stacked: bool, gradient_from: str | None) -> None:
    """Position one item, stacked or side by side."""
    if stacked:
        step = font.height * scale + 2
        top = (c.height - (len(texts) * step - 2)) // 2
        _draw(c, text, colour, c.width // 2, top + index * step, font, scale,
              "center", gradient_from)
    else:
        widths = [font.measure(t) * scale for t in texts]
        gap = 8
        total = sum(widths) + gap * (len(texts) - 1)
        x = (c.width - total) // 2 + sum(widths[:index]) + gap * index
        y = (c.height - font.height * scale) // 2
        _draw(c, text, colour, x, y, font, scale, "left", gradient_from)


def _layout(c: Canvas, items, texts, font, scale, stacked, gradient, gradient_from):
    for index, (text, colour) in enumerate(items):
        _place(c, texts, index, text, colour, font, scale, stacked,
               gradient_from if gradient else None)
