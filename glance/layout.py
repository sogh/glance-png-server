"""Where things sit on the strip.

One principle, arrived at the hard way and worth stating once:

    **Content is centred as a single group, inside a margin, and the blank
    that is left over lands at the two edges.**

Three corollaries, each of which was a bug before it was a rule.

*As a single group.* The board name, the crests and the result on a scoreboard
are one thing, centred together. Centre them separately -- or pin the label to
one edge and the result to the other -- and a longer board name visibly shoves
the middle across, so `MARINERS` and `WPBL` do not line up with each other.

*Inside a margin.* The device pans from one app straight into the next with
nothing between them, so a pane inked from edge to edge runs into its
neighbour and the two read as one muddle. The margin is a floor, not a fixed
inset: narrow content is simply centred and already clears it, and only a wide
row is pushed. When a row cannot fit even so, it sheds its least important
part rather than crossing the line.

*Measure, then place.* A row's width is not known until it is full, so packing
and drawing in one pass can only ever left-align. Two passes, always.

Decoration follows the content rather than the panel: leaves belong beside the
words, not out at the edges with a gulf between.
"""

from __future__ import annotations

from typing import Iterable, Sequence

# Blank kept at each edge. Roughly the width of a 5x7 glyph -- enough to read
# as a deliberate gap when two panes meet, small enough not to cost a word.
MARGIN = 8


def centre(available: int, content: int, margin: int = MARGIN) -> int:
    """Left edge for a block of `content` centred in `available`.

    The margin is a floor: content that already clears it is left alone, and
    content wider than the space is pushed to the margin rather than off it.
    """
    return max(margin, (available - content) // 2)


def span(widths: Sequence[int], gap: int) -> int:
    """Total width of several items laid in a row with `gap` between them."""
    widths = list(widths)
    if not widths:
        return 0
    return sum(widths) + gap * (len(widths) - 1)


def row(available: int, widths: Sequence[int], gap: int,
        margin: int = MARGIN) -> list[int]:
    """x for each item in a row, the row centred as one group."""
    x = centre(available, span(widths, gap), margin)
    out = []
    for width in widths:
        out.append(x)
        x += width + gap
    return out


def fits(available: int, widths: Iterable[int], gap: int,
         margin: int = MARGIN) -> bool:
    return span(list(widths), gap) <= available - 2 * margin
