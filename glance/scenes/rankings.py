"""A poll, as far down it as the strip will take.

The companion to `scores`: that one asks "how did our team do", this one asks
"who is on top". It reads the published poll rather than any team's schedule,
so showing twenty-five teams costs one cached request, not twenty-five.
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register
from .scores import _board


def _source(ctx: RenderContext, params: dict[str, Any]):
    board = _board(ctx, params)
    source = getattr(board, "source", None) if board is not None else None
    return board, (source if hasattr(source, "ranked_teams") else None)


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    _, source = _source(ctx, params)
    if source is None:
        return False
    try:
        return bool(source.ranked_teams(4))
    except Exception:  # noqa: BLE001 - a bad feed must not stall the channel
        return False


@register("rankings", available=_available,
          description="The top of a poll, as many as fit",
          params=[
              Param("board", "select", None, options="@boards",
                    help="Which configured scoreboard's poll to read"),
              Param("count", "number", 0, minimum=0, maximum=25,
                    help="How many to show; 0 fits as many as the strip takes"),
              Param("style", "select", "crests", options=["crests", "text"],
                    help="Team crests, or rank and abbreviation as text"),
              Param("accent", "color", "amber", options="@colors"),
              Param("label", "bool", True, help="Name the poll"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_rankings(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small = get_font("3x5")
    accent = params.get("accent", "amber")

    board, source = _source(ctx, params)
    if source is None:
        c.centered("RANKINGS", dim(accent, 0.9), small, y=6)
        c.centered("no poll configured", "dim", small, y=17)
        return c

    asked = int(params.get("count", 0) or 0)
    entries = source.ranked_teams(asked or 25)
    if not entries:
        c.centered(getattr(source, "poll_name", "POLL"), dim(accent, 0.9), small, y=6)
        c.centered(str(source.last_error or "poll unavailable")[:44], "dim", small,
                   y=17, max_width=c.width - 4)
        return c

    tag = getattr(source, "poll_name", "") if bool(params.get("label", True)) else ""
    if str(params.get("style", "crests")) == "text":
        return _as_text(c, entries, asked, tag, accent, small)
    return _as_crests(ctx, c, entries, asked, tag, accent, small)


def _rows(c: Canvas, height: int) -> list[int]:
    """Top y of each row that fits, with the leftovers spread as padding."""
    count = max(1, c.height // height)
    spare = c.height - count * height
    gap = spare // max(1, count)
    return [i * (height + gap) + gap // 2 for i in range(count)]


def _as_crests(ctx, c, entries, asked, tag, accent, small):
    store = getattr(ctx, "logos", None)
    size = getattr(store, "size", 16) if store is not None else 16
    rows = _rows(c, size)

    # Rank number then crest. A team whose logo will not read at this size
    # falls back to its abbreviation in the same slot -- in a list of many,
    # one text cell reads as a team without a usable crest, where in a
    # head-to-head it would look like a rendering fault.
    x, row = 2, 0
    if tag:
        c.text(x, rows[0] + (size - small.height) // 2, tag, dim(accent, 0.8), small)
        x += small.measure(tag) + 5

    shown = 0
    for side in entries:
        crest = store.get(side.key or side.abbrev, side.logo) if (store and side.logo) else None
        label = str(side.rank or "")
        body = size if crest is not None else small.measure(side.abbrev)
        need = small.measure(label) + 2 + body + 6
        if x + need > c.width:
            row += 1
            if row >= len(rows):
                break
            x = 2
            need = small.measure(label) + 2 + body + 6
            if x + need > c.width:
                break
        top = rows[row]
        c.text(x, top + (size - small.height) // 2, label, dim(accent, 0.85), small)
        x += small.measure(label) + 2
        if crest is not None:
            c.blit(crest, x, top)
        else:
            c.text(x, top + (size - small.height) // 2, side.abbrev, "white", small)
        x += body + 6
        shown += 1
        if asked and shown >= asked:
            break
    return c


def _as_text(c, entries, asked, tag, accent, small):
    rows = _rows(c, small.height + 2)
    x, row = 2, 0
    if tag:
        c.text(x, rows[0], tag, dim(accent, 0.8), small)
        x += small.measure(tag) + 5

    shown = 0
    for side in entries:
        label, name = str(side.rank or ""), side.abbrev
        need = small.measure(label) + 2 + small.measure(name) + 6
        if x + need > c.width:
            row += 1
            if row >= len(rows):
                break
            x = 2
        top = rows[row]
        c.text(x, top, label, dim(accent, 0.85), small)
        x += small.measure(label) + 2
        c.text(x, top, name, "white", small)
        x += small.measure(name) + 6
        shown += 1
        if asked and shown >= asked:
            break
    return c
