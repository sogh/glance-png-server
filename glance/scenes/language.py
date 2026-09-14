"""A word or phrase in another language, and what it means.

Two small decisions carry most of the value.

**The article is coloured separately.** "la granja" and "el huerto" differ in
a way English does not have, and gender is the thing beginners get wrong for
years. Drawing "la" in its own colour every time costs nothing and puts the
distinction in front of you on every single card.

**The accents are real.** The 5x7 font grew a composed set of diacritics for
this -- see fonts.py -- because "el año" and "el ano" are different words and
a panel that quietly renders the second one is worse than no panel.
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register

# Feminine and masculine, in both languages. Colouring by gender rather than
# by word means "la" reads the same in Spanish and French, which is correct --
# they are the same gender in both.
FEMININE = {"la", "las", "una", "unas", "les", "une"}


def _deck(ctx: RenderContext, params: dict[str, Any]):
    books = getattr(ctx, "vocabulary", None)
    if books is None:
        return None
    wanted = str(params.get("language", "") or "").strip()
    if wanted:
        return books.get(wanted)
    first = books.languages
    return books.get(first[0]) if first else None


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    deck = _deck(ctx, params)
    return bool(deck and len(deck))


@register("language", available=_available,
          description="A word or phrase in another language, and what it means",
          params=[
              Param("language", "select", None, options="@languages",
                    help="Which deck: es, fr, or whatever you add"),
              Param("rotate", "number", 900, minimum=30, maximum=86400,
                    help="Seconds each word holds before the next one"),
              Param("shuffle", "bool", True,
                    help="Reshuffle the deck daily rather than run it in order"),
              Param("reveal", "number", 0, minimum=0, maximum=1,
                    help="Hide the meaning until this far through the slot; "
                         "0 shows it throughout"),
              Param("color", "color", "white", options="@colors"),
              Param("article_color", "color", "amber", options="@colors",
                    help="The gender-carrying article, drawn apart"),
              Param("gloss_color", "color", "sky", options="@colors"),
              Param("feminine_color", "color", None, options="@colors",
                    help="Optional second article colour, for feminine nouns"),
              Param("note", "bool", True, help="Show the pronunciation hint"),
              Param("label", "bool", False, help="Name the language"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_language(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small, big = get_font("3x5"), get_font("5x7")

    deck = _deck(ctx, params)
    if deck is None or not len(deck):
        c.centered("VOCABULARY", dim("amber", 0.9), small, y=6)
        c.centered("no deck configured", "dim", small, y=17)
        return c

    rotate = int(params.get("rotate", 900) or 900)
    entry = deck.at(ctx.now, rotate, bool(params.get("shuffle", True)))
    if entry is None:
        c.centered(deck.label[:24], dim("amber", 0.9), small, y=6)
        c.centered("empty deck", "dim", small, y=17)
        return c

    reveal = max(0.0, min(1.0, float(params.get("reveal", 0) or 0)))
    shown = reveal <= 0.0 or deck.progress(ctx.now, rotate) >= reveal

    top = 0
    if bool(params.get("label", False)):
        c.text(2, 0, deck.label[:12], dim("amber", 0.6), small)
        top = small.height + 1

    note = entry.note if bool(params.get("note", True)) else ""
    # The note only earns its row if the term and gloss have already had
    # theirs; a squeezed three-line card reads worse than a clear two-line one.
    lines = 2 + (1 if note else 0)
    room = c.height - top
    scale = 2 if (big.measure(entry.term) * 2 <= c.width - 6
                  and room >= 14 + 2 + small.height + (small.height + 1 if note else 0)) else 1

    term_h = big.height * scale
    block = term_h + 2 + small.height + ((small.height + 1) if note else 0)
    y = top + max(0, (room - block) // 2)

    _term(c, entry, y, big, scale, params)
    y += term_h + 2

    if shown:
        c.text(c.width // 2, y, entry.gloss, params.get("gloss_color", "sky"),
               small, "center", c.width - 4)
    else:
        # A blank half-card looks like a failed render, so say what it is.
        c.text(c.width // 2, y, "?", dim("grey", 0.6), small, "center")
    y += small.height + 1

    if note and y + small.height <= c.height:
        c.text(c.width // 2, y, note, dim("grey", 0.7), small, "center",
               c.width - 4)
    return c


def _term(c: Canvas, entry, y: int, font, scale: int, params: dict[str, Any]) -> None:
    """The term, with its article in a colour of its own."""
    colour = params.get("color", "white")
    article = entry.article
    if not article:
        c.text(c.width // 2, y, entry.term, colour, font, "center",
               c.width - 4, scale)
        return

    feminine = params.get("feminine_color")
    article_colour = (feminine if feminine and article.lower() in FEMININE
                      else params.get("article_color", "amber"))

    gap = 2 * scale
    widths = (font.measure(article) * scale, font.measure(entry.rest) * scale)
    x = max(2, (c.width - (widths[0] + gap + widths[1])) // 2)
    c.text(x, y, article, article_colour, font, "left", None, scale)
    c.text(x + widths[0] + gap, y, entry.rest, colour, font, "left", None, scale)
