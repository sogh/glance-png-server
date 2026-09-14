"""A welcome banner: big title, small subtitle, optional decoration.

Built for mode takeovers -- while visitors are here the calendar panels have
nothing useful to say to a guest, so they hand their slot to this instead.
Nothing about it is mode-specific though; it is just a title card.

A banner can also be drawn wider than one panel and served in slices, so two
channels shown back to back read as one long sign rather than as the same card
twice. Set the same `span` on every entry and give each a different `part`:

    today:  { scene: banner, params: { span: 2, part: 1, title: ... } }
    next:   { scene: banner, params: { span: 2, part: 2, title: ... } }

The type is laid out once across the full width and then cut, so a letter
landing on the seam is split down the middle rather than drawn twice.
"""

from __future__ import annotations

from typing import Any

from ..canvas import MAX_PANEL_WIDTH, Canvas
from ..fonts import get_font
from ..palette import dim, parse
from .base import Param, RenderContext, register

# A pixel evergreen: layered boughs over a short trunk. Drawn rather than
# loaded so it takes the accent colour and needs no asset shipped with it.
TREE = (
    "...#...",
    "..###..",
    ".#####.",
    "..###..",
    ".#####.",
    "#######",
    ".#####.",
    "#######",
    "...#...",
    "...#...",
)
TREE_W = len(TREE[0])
TREE_H = len(TREE)


def _tree(c: Canvas, x: int, y: int, color, trunk) -> None:
    for row, line in enumerate(TREE):
        for col, ch in enumerate(line):
            if ch != "#":
                continue
            # The last two rows are the trunk, which wants to be woodier than
            # the needles or the whole thing reads as a diamond.
            c.pixel(x + col, y + row, trunk if row >= TREE_H - 2 else color)


@register("banner", description="A welcome banner -- title, subtitle, evergreens",
          params=[
              Param("title", "text", "WELCOME", help="The big line"),
              Param("subtitle", "text", "", help="The small line under it"),
              Param("color", "color", "white", options="@colors"),
              Param("accent", "color", "mint", options="@colors"),
              Param("background", "color", "black", options="@colors"),
              Param("motif", "select", "trees", options=["trees", "rules", "none"],
                    help="Evergreens either side, plain rules, or nothing"),
              Param("scale", "number", 0, minimum=0, maximum=3,
                    help="Title size; 0 fits the widest that will go"),
              Param("span", "number", 1, minimum=1, maximum=2,
                    help="Lay the banner out across this many panels"),
              Param("part", "number", 1, minimum=1, maximum=2,
                    help="Which slice of a spanned banner this channel serves"),
          ])
def render_banner(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    # Draw at full span, then cut. Laying each slice out on its own would put
    # a second copy of the title in the second panel; what is wanted is the
    # same sign, continued.
    span = max(1, min(MAX_PANEL_WIDTH // max(1, ctx.width), int(params.get("span", 1) or 1)))
    part = max(1, min(span, int(params.get("part", 1) or 1)))
    c = Canvas(width=ctx.width * span)
    c.clear(params.get("background", "black"))

    title = str(params.get("title", "") or "").strip()
    subtitle = str(params.get("subtitle", "") or "").strip()
    color = params.get("color", "white")
    accent = params.get("accent", "mint")
    motif = str(params.get("motif", "trees"))

    left, right = 2, c.width - 2
    top_edge, bottom_edge = 0, c.height
    if motif == "trees":
        top = (c.height - TREE_H) // 2
        trunk = dim(accent, 0.45)
        _tree(c, 3, top, accent, trunk)
        _tree(c, c.width - TREE_W - 3, top, accent, trunk)
        left, right = TREE_W + 8, c.width - TREE_W - 8
    elif motif == "rules":
        c.fill_rect(0, 0, c.width, 1, accent)
        c.fill_rect(0, c.height - 1, c.width, 1, accent)
        c.fill_rect(0, 1, c.width, 1, dim(accent, 0.3))
        c.fill_rect(0, c.height - 2, c.width, 1, dim(accent, 0.3))
        top_edge, bottom_edge = 3, c.height - 3

    room = max(1, right - left)
    headroom = max(1, bottom_edge - top_edge)
    big, small = get_font("5x7"), get_font("3x5")

    gap = 3
    def block_height(at: int) -> int:
        return big.height * at + (gap + small.height if subtitle else 0)

    # Pick the largest whole-pixel scale the title fits at, in BOTH directions
    # -- checking only the width let a short title grow until it collided with
    # the rules. Whole numbers only; there is no half pixel to round into on a
    # panel this size.
    asked = int(params.get("scale", 0) or 0)
    if asked:
        scale = max(1, asked)
    else:
        scale = 1
        while (scale < 3
               and big.measure(title) * (scale + 1) <= room
               and block_height(scale + 1) <= headroom):
            scale += 1

    centre = (left + right) // 2
    top = top_edge + (headroom - block_height(scale)) // 2
    c.text(centre, top, title, color, big, "center", room, scale)
    if subtitle:
        c.text(centre, top + big.height * scale + gap, subtitle,
               dim(accent, 0.9), small, "center", room)

    if span == 1:
        return c
    cut = ctx.canvas()
    cut.image.paste(c.image.crop(((part - 1) * ctx.width, 0, part * ctx.width, c.height)), (0, 0))
    return cut
