"""Text that breathes between white and a colour.

Written as an animated PNG. If the panel does not decode APNG it shows frame
zero, which is the all-white state -- still perfectly readable.

    /s/pulse.png?items=ADA:amber,GRACE:sky
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import mix
from .base import Param, RenderContext, register

DEFAULT_ITEMS = "ADA:amber,GRACE:sky"


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


@register("pulse", description="Names in a colour, over time or across the letters",
          params=[
              Param("items", "text", DEFAULT_ITEMS,
                    help="NAME:colour, comma separated"),
              Param("mode", "select", "gradient", options=["gradient", "pulse"],
                    help="gradient ramps across the letters; pulse animates "
                         "(this panel does not decode APNG)"),
              Param("layout", "select", "column", options=["column", "row"],
                    help="Stack the names, or set them side by side"),
              Param("from", "color", "white", options="@colors",
                    help="Colour each name starts at"),
              Param("font", "select", "5x7", options="@fonts",
                    help="Typeface for the names"),
              Param("scale", "number", None, minimum=1, maximum=4,
                    help="Text size; blank fits the largest that will go"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_pulse(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    items = parse_items(params.get("items", DEFAULT_ITEMS))
    if not items:
        c = ctx.canvas()
        c.clear("black")
        c.centered("(no items)", "dim", "3x5")
        return c

    font = get_font(str(params.get("font", "5x7")))
    background = params.get("background", "black")

    texts = [t for t, _ in items]
    stacked = str(params.get("layout", "column" if len(items) > 1 else "row")) == "column"
    fits = _fit_scale(font, texts, ctx.width - 6, stacked, ctx.height)
    requested = int(params.get("scale", 0))
    # Clamp rather than obey: a scale that does not fit clips the glyphs, and
    # a half-drawn name is worse than a smaller one.
    scale = min(requested, fits) if requested > 0 else fits

    # The gradient runs across the letters, not across time. It was written as
    # an animation first; the device renders frame zero of an APNG and stops,
    # so the same white-to-colour transition was moved into one frame, where
    # it is visible on hardware that will never animate.
    c = ctx.canvas()
    c.clear(background)
    _layout(c, items, texts, font, scale, stacked, gradient=True,
            gradient_from=params.get("from", "white"))
    return c


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
