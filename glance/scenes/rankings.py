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
              Param("margin", "number", 8, minimum=0, maximum=40,
                    help="Blank kept at each edge, so the pane separates from "
                         "its neighbours as the device pans past"),
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
    margin = max(0, int(params.get("margin", 8) or 0))
    if str(params.get("style", "crests")) == "text":
        return _as_text(c, entries, asked, tag, accent, small, margin)
    return _as_crests(ctx, c, entries, asked, tag, accent, small, margin)


def _rows(c: Canvas, height: int) -> list[int]:
    """Top y of each row that fits, with the leftovers spread as padding."""
    count = max(1, c.height // height)
    spare = c.height - count * height
    gap = spare // max(1, count)
    return [i * (height + gap) + gap // 2 for i in range(count)]


def _pack(cells: list[int], room: int, rows: int, gap: int) -> list[list[int]]:
    """Greedily fill each row, left to right, within `room`.

    Two passes rather than one: the width of a row is not known until it is
    full, and a row cannot be centred until its width is known. Packing and
    drawing in the same loop is what pinned everything to the left edge.
    """
    out: list[list[int]] = []
    current: list[int] = []
    used = 0
    for index, width in enumerate(cells):
        need = width + (gap if current else 0)
        if current and used + need > room:
            out.append(current)
            if len(out) >= rows:
                return out
            current, used = [], 0
            need = width
        current.append(index)
        used += need
    if current:
        out.append(current)
    return out[:rows]


def _centred(c: Canvas, widths: list[int], indexes: list[int], gap: int,
             margin: int) -> int:
    """Left edge for a row, so its content sits in the middle of the strip."""
    span = sum(widths[i] for i in indexes) + gap * (len(indexes) - 1)
    return max(margin, (c.width - span) // 2)


def _lay_out(c, cells, rows, gap, margin, asked):
    """Pack cells into rows and yield (x, top, cell) for each, centred.

    Two passes: a row's width is not known until it is full, and it cannot be
    centred until its width is known. Packing and drawing in one loop is what
    pinned everything to the left edge.
    """
    widths = [cell[0] for cell in cells]
    packed = _pack(widths, c.width - 2 * margin, len(rows), gap)
    drawn = 0
    for row_index, indexes in enumerate(packed):
        x = _centred(c, widths, indexes, gap, margin)
        for i in indexes:
            kind = cells[i][1]
            if kind == "team":
                if asked and drawn >= asked:
                    return
                drawn += 1
            yield x, rows[row_index], cells[i]
            x += widths[i] + gap


def _as_crests(ctx, c, entries, asked, tag, accent, small, margin=8):
    store = getattr(ctx, "logos", None)
    size = getattr(store, "size", 16) if store is not None else 16

    # A team whose logo will not read at this size falls back to its
    # abbreviation in the same slot -- in a list of many, one text cell reads
    # as a team without a usable crest, where in a head-to-head it would look
    # like a rendering fault.
    crests = [store.get(e.key or e.abbrev, e.logo, size)
              if (store and e.logo) else None for e in entries]

    cells = []
    if tag:
        cells.append((small.measure(tag), "tag", tag))
    for index, entry in enumerate(entries):
        rank = str(entry.rank or "")
        body = size if crests[index] is not None else small.measure(entry.abbrev)
        cells.append((small.measure(rank) + 2 + body, "team", index))

    middle = lambda top: top + (size - small.height) // 2
    for x, top, (_, kind, payload) in _lay_out(c, cells, _rows(c, size), 6,
                                               margin, asked):
        if kind == "tag":
            c.text(x, middle(top), payload, dim(accent, 0.8), small)
            continue
        entry = entries[payload]
        rank = str(entry.rank or "")
        c.text(x, middle(top), rank, dim(accent, 0.85), small)
        x += small.measure(rank) + 2
        if crests[payload] is not None:
            c.blit(crests[payload], x, top)
        else:
            c.text(x, middle(top), entry.abbrev, "white", small)
    return c


def _as_text(c, entries, asked, tag, accent, small, margin=8):
    cells = []
    if tag:
        cells.append((small.measure(tag), "tag", tag))
    for index, entry in enumerate(entries):
        rank = str(entry.rank or "")
        cells.append((small.measure(rank) + 2 + small.measure(entry.abbrev),
                      "team", index))

    for x, top, (_, kind, payload) in _lay_out(c, cells,
                                               _rows(c, small.height + 2), 6,
                                               margin, asked):
        if kind == "tag":
            c.text(x, top, payload, dim(accent, 0.8), small)
            continue
        entry = entries[payload]
        rank = str(entry.rank or "")
        c.text(x, top, rank, dim(accent, 0.85), small)
        c.text(x + small.measure(rank) + 2, top, entry.abbrev, "white", small)
    return c
