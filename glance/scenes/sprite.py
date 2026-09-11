"""Text with a piece of pixel art set into it.

    /s/sprite.png?before=It's&sprite=sweatpants&after=season!
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..sprites import SPRITES, draw_sprite, get_sprite
from .base import RenderContext, register


@register("sprite", description="Text with a pixel-art sprite set into it")
def render_sprite(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))

    name = str(params.get("sprite", "sweatpants"))
    sprite = get_sprite(name)
    if sprite is None:
        c.centered(f"no sprite: {name}", "red", "3x5", max_width=c.width - 4)
        return c

    before = str(params.get("before", ""))
    after = str(params.get("after", ""))
    color = params.get("color", "white")
    font = get_font(str(params.get("font", "5x7")))
    gap = int(params.get("gap", 5))

    sprite_scale = max(1, int(params.get("sprite_scale", 1)))
    sprite_w = sprite.width * sprite_scale

    # The sprite is the fixed part; the text gets whatever is left. On a
    # narrow panel that can be very little, so squeeze the gaps first.
    room = c.width - 4 - sprite_w
    while gap > 1 and room - gap * 2 < 12:
        gap -= 1
    avail = max(0, room - gap * 2)

    # Largest whole scale where both strings fit beside the sprite.
    ceiling = min(4, max(1, int(params.get("scale", 4))))
    scale = 1
    for candidate in range(ceiling, 0, -1):
        if ((font.measure(before) + font.measure(after)) * candidate <= avail
                and font.height * candidate <= c.height):
            scale = candidate
            break

    before_w = font.measure(before) * scale
    after_w = font.measure(after) * scale

    # Even at scale 1 it may not fit -- truncate rather than run off the panel,
    # splitting the available room in proportion to each string's natural size.
    if before_w + after_w > avail:
        natural = max(1, before_w + after_w)
        before = font.truncate(before, int(avail * before_w / natural) // scale)
        after = font.truncate(after, int(avail * after_w / natural) // scale)
        before_w = font.measure(before) * scale
        after_w = font.measure(after) * scale

    total = before_w + after_w + sprite_w + gap * 2

    x = (c.width - total) // 2
    text_y = (c.height - font.height * scale) // 2
    sprite_y = (c.height - sprite.height * sprite_scale) // 2

    if before:
        c.text(x, text_y, before, color, font, "left", None, scale)
    x += before_w + gap
    draw_sprite(c, sprite, x, sprite_y, scale=sprite_scale)
    x += sprite_w + gap
    if after:
        c.text(x, text_y, after, color, font, "left", None, scale)
    return c


@register("sprites", description="Every sprite, for checking the art")
def render_sprite_sheet(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear("black")
    x = 2
    for sprite in SPRITES.values():
        if x + sprite.width > c.width:
            break
        draw_sprite(c, sprite, x, (c.height - sprite.height) // 2)
        x += sprite.width + 4
    return c
