"""Small utility scenes: a clock, arbitrary configured text, and a blank."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from ..layout import centre
from ..seasons import days_until
from ..sprites import SPRITES, draw_sprite
from .base import Param, RenderContext, register


@register("clock", description="Time and date",
          params=[
              Param("hour24", "bool", False, help="24-hour clock"),
              Param("date", "bool", True, help="Show the date line"),
              Param("lead", "number", 0, minimum=0, maximum=900,
                    help="Seconds to shift forward; set to half your refresh "
                         "interval so the error is centred rather than always slow"),
              Param("color", "color", "white", options="@colors"),
              Param("accent", "color", "sky", options="@colors"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_clock(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    hour24 = bool(params.get("hour24", False))
    color = params.get("color", "white")

    # The device caches this image and redraws it until its next refresh, so a
    # clock rendered at fetch time is correct once and then drifts behind for
    # the rest of the interval. Setting `lead` to half the refresh interval
    # centres the error instead: with refresh=300, lead=150 means the panel is
    # at worst 2.5 minutes out either way rather than up to 5 minutes slow.
    now = ctx.now + timedelta(seconds=int(params.get("lead", 0)))

    if hour24:
        stamp, meridiem = now.strftime("%H:%M"), ""
    else:
        stamp = f"{now.hour % 12 or 12}:{now.minute:02d}"
        meridiem = "AM" if now.hour < 12 else "PM"

    show_date = bool(params.get("date", True))
    top = 4 if show_date else 9

    # Monospaced digits so the layout does not jitter as the minutes tick over.
    # The meridiem sits beside the time, baseline-aligned, rather than being
    # appended to the date line where it reads as part of the date.
    mono, small = get_font("5x7mono"), get_font("3x5")
    time_w = mono.measure(stamp) * 2
    gap = 4
    total = time_w + (gap + small.measure(meridiem) if meridiem else 0)
    x = (c.width - total) // 2

    c.text(x, top, stamp, color, mono, scale=2)
    if meridiem:
        c.text(x + time_w + gap, top + mono.height * 2 - small.height,
               meridiem, dim(color, 0.7), small)
    if show_date:
        line = now.strftime("%a %d %b").upper().replace(" 0", " ")
        c.centered(line, dim(params.get("accent", "sky"), 0.9), "3x5", y=23)
    return c


@register("date", description="Day and date, no clock",
          params=[
              Param("year", "bool", True, help="Include the year"),
              Param("rule", "bool", True, help="Hairline along the bottom"),
              Param("color", "color", "white", options="@colors"),
              Param("accent", "color", "sky", options="@colors"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_date(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    """The date on its own.

    A clock on a panel that refreshes once a minute is a liability; a date is
    correct all day and needs no such apology.
    """
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    accent = params.get("accent", "sky")

    weekday = ctx.now.strftime("%A").upper()
    day = str(ctx.now.day)
    month = ctx.now.strftime("%B").upper()
    line2 = f"{day} {month}"
    if params.get("year", True):
        line2 += f" {ctx.now.year}"

    font = get_font("5x7")
    scale = 2 if font.measure(weekday) * 2 <= c.width - 8 else 1
    c.centered(weekday, params.get("color", "white"), font,
               y=4 if scale == 2 else 8, max_width=c.width - 6, scale=scale)
    c.centered(line2, dim(accent, 0.95), "3x5", y=21, max_width=c.width - 6)

    if params.get("rule", True):
        c.hline(0, 31, c.width, dim(accent, 0.3))
    return c


@register("text", description="Fixed text from the channel config",
          params=[
              Param("text", "text", "", help="The main line"),
              Param("sub", "text", None, help="Smaller line beneath"),
              Param("color", "color", "white", options="@colors"),
              Param("sub_color", "color", None, options="@colors"),
              Param("font", "select", "5x7", options="@fonts",
                    help="Typeface for the body text"),
              Param("scale", "number", None, minimum=1, maximum=4,
                    help="Blank fits it automatically"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_text(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    body = str(params.get("text", ""))
    if not body:
        c.centered("(no text)", "dim", "3x5")
        return c

    color = params.get("color", "white")
    sub = params.get("sub")
    font = get_font(str(params.get("font", "5x7")))
    avail = c.width - 6

    scale = int(params.get("scale", 0)) or (2 if font.measure(body) * 2 <= avail else 1)
    lines = [body] if font.measure(body) * scale <= avail else font.wrap(body, avail // scale)[:2]

    block = len(lines) * (font.height * scale + 2) - 2
    sub_h = get_font("3x5").height + 4 if sub else 0
    top = max(0, (c.height - block - sub_h) // 2)
    c.text_block(c.width // 2, top, lines, color, font, "center", leading=2, scale=scale)
    if sub:
        c.centered(str(sub), params.get("sub_color", dim(color, 0.6)), "3x5",
                   y=top + block + 4)
    return c


@register("blank", description="An intentionally dark panel",
          params=[Param("background", "color", "black", options="@colors")])
def render_blank(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    return c


def countdown_target(ctx, params) -> tuple[int, str] | None:
    """Days remaining and a default label, or None if nothing is configured.

    Three ways to say when:

      season: fall            the real equinox, recomputed every year
      date: 12-25             every year, rolling over once it passes
      date: 2026-12-25        once

    The season and the MM-DD form both renew themselves, which is the point.
    A countdown pinned to a fixed date spends the eleven months after it
    counting upwards, and a countdown to "fall" pinned to 09-22 is wrong about
    one year in three -- the equinox moves.
    """
    season = str(params.get("season", "") or "").strip()
    if season:
        try:
            days = days_until(
                ctx.now, season,
                hemisphere=str(params.get("hemisphere", "north")),
                meteorological=bool(params.get("meteorological", False)))
        except ValueError:
            return None
        return days, season.upper()

    raw = str(params.get("date", "") or "").strip()
    if not raw:
        return None
    try:
        if len(raw) <= 5 and "-" in raw:
            # MM-DD: this year's, or next year's once it has gone by.
            month, day = (int(x) for x in raw.split("-"))
            target = date(ctx.today.year, month, day)
            if target < ctx.today:
                target = date(ctx.today.year + 1, month, day)
        else:
            target = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return (target - ctx.today).days, ""


def _countdown_available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    """A countdown can schedule itself.

    `within: 30` keeps it out of the rotation until the target is a month off,
    which is what you want from a seasonal panel -- otherwise a countdown to
    autumn spends nine months of the year taking a slot to say "271".
    """
    if params.get("always"):
        return True
    found = countdown_target(ctx, params)
    if found is None:
        return False
    days, _ = found
    within = int(params.get("within", 0) or 0)
    return True if within <= 0 else 0 <= days <= within


@register("countdown", available=_countdown_available,
          description="Days remaining until a date or a season",
          params=[
              Param("date", "text", None,
                    help="YYYY-MM-DD for a one-off, or MM-DD to repeat yearly"),
              Param("season", "select", None,
                    options=["", "spring", "summer", "autumn", "fall", "winter"],
                    help="Count to the real equinox or solstice instead of a date"),
              Param("hemisphere", "select", "north", options=["north", "south"],
                    help="Which half of the planet the season belongs to"),
              Param("meteorological", "bool", False,
                    help="Use the 1st of the month rather than the astronomical moment"),
              Param("motif", "select", "none", options=["none", "leaves"],
                    help="Decoration around the number; leaves for autumn"),
              Param("gradient_to", "color", None, options="@colors",
                    help="Ramp the number from `color` to this across its digits"),
              Param("within", "number", 0, minimum=0, maximum=400,
                    help="Only appear when the target is this many days off; "
                         "0 shows it always"),
              Param("label", "text", "", help="What it is counting to"),
              Param("color", "color", "amber", options="@colors"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_countdown(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    found = countdown_target(ctx, params)
    if found is None:
        c.centered("no date set", "red", "3x5")
        return c

    days, default_label = found
    label = str(params.get("label", "") or default_label).upper()
    color = params.get("color", "amber")

    motif = str(params.get("motif", "none"))
    ramp = params.get("gradient_to")

    if days == 0:
        text = label or "TODAY"
        font = get_font("5x7")
        width = font.measure(text) * 2
        if motif == "leaves":
            _leaves(c, centre(c.width, width), centre(c.width, width) + width)
        if ramp:
            c.text_gradient(c.width // 2, 12, text, color, ramp, font, "center", 2)
        else:
            c.centered(text, color, font, y=12, scale=2)
        return c

    number = str(abs(days))
    word = "DAY" if abs(days) == 1 else "DAYS"
    tail = word if days > 0 else f"{word} AGO"
    scale = 3 if len(number) <= 3 else 2
    big = get_font("5x7mono")
    width = big.measure(number) * scale

    caption = f"{tail} TO {label}" if label else tail
    # The caption is usually wider than the number, and the leaves hug
    # whichever is wider -- otherwise they sit beside a narrow "6" and overlap
    # "DAYS TO FALL" underneath it.
    content = max(width, get_font("3x5").measure(caption))
    if motif == "leaves":
        _leaves(c, centre(c.width, content), centre(c.width, content) + content)

    # A ramp needs something to ramp across: text_gradient steps per character,
    # so a single digit lands on the far end and the start colour is simply
    # lost. "6 DAYS" would come out red with no amber in it at all.
    if ramp and len(number) > 1:
        c.text_gradient(c.width // 2, 3, number, color, ramp, big, "center", scale)
    else:
        c.centered(number, color, big, y=3, scale=scale)

    c.centered(caption, dim(color, 0.8), "3x5", y=26)
    return c


# Which leaf, what colour, and how far OUT from the text it sits -- see
# layout.py: decoration follows the content, not the panel. Measured outward
# from the edge of the words, so the leaves stay beside them however wide the
# number gets instead of floating out at the margins with a gulf between.
#
# Fixed rather than random. A scatter that changed on every fetch would
# flicker between refreshes and read as a rendering fault rather than as
# weather; this is the same arrangement every time, chosen once by eye.
_FALL = (
    (1, 1, "maple", "#e07414"),
    (14, 11, "oak", "#a8481a"),
    (4, 20, "leaf", "#c8641c"),
    (20, 2, "leaf", "#8f3f12"),
    (11, 25, "leaf", "#d2891f"),
)


def _leaves(c: Canvas, left_edge: int, right_edge: int) -> None:
    """Autumn leaves either side of the text, working outward from it."""
    for out, y, name, colour in _FALL:
        sprite = SPRITES.get(name)
        if sprite is None:
            continue
        # Just past the words on the left, and its mirror on the right.
        for x in (left_edge - out - sprite.width, right_edge + out):
            if 0 <= x and x + sprite.width <= c.width:
                draw_sprite(c, sprite, x, y, override={"#": colour})


@register("panels", description="Test card: shows the physical 64px modules",
          params=[Param("module", "number", 64, minimum=8, maximum=192,
                        help="Module width; 64 unless your hardware is unusual")])
def render_panels(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    """A test card for working out what your hardware actually is.

    A Glance is built from 64x32 LED modules chained together, so a 192px
    display is three of them showing one continuous image -- not three
    separate screens. This draws each module's boundary and number, plus
    markers in the extreme corners.

    Read it like this:
      - count the numbered blocks -> that is your module count
      - all four corner markers visible -> the width is right
      - corners missing, or text squashed -> the panel is not this wide
    """
    c = ctx.canvas()
    c.clear("black")
    module = int(params.get("module", 64))
    colors = ["red", "green", "sky", "amber", "magenta", "mint"]

    # Centre the block properly. An off-centre test card is worse than no test
    # card: it looks exactly like the panel shifting the image, which is the
    # thing you are using it to rule out.
    big, small = get_font("5x7"), get_font("3x5")
    block = big.height * 2 + 3 + small.height
    top = (c.height - block) // 2

    count = max(1, -(-c.width // module))
    for i in range(count):
        x0 = i * module
        w = min(module, c.width - x0)
        color = colors[i % len(colors)]
        c.rect(x0, 0, w, c.height, color)
        c.text(x0 + w // 2, top, str(i + 1), color, big, "center", w - 6, scale=2)
        c.text(x0 + w // 2, top + big.height * 2 + 3, f"{x0}-{x0 + w - 1}",
               dim(color, 0.8), small, "center", w - 4)

    # Corner pixels: if any is dark on the real panel, the image is being
    # cropped or scaled rather than shown 1:1.
    for x in (0, c.width - 1):
        for y in (0, c.height - 1):
            c.pixel(x, y, "hotwhite")
    return c


@register("alignment", description="Test card: are the top and bottom rows reaching the panel?",
          params=[])
def render_alignment(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    """Answers one question: is every row of the image actually displayed?

    Row 0 is red and row 31 is blue, each two pixels deep. If you cannot see
    the red, the top is being cut; if you cannot see the blue, the bottom is.
    The side ruler ticks every four rows so a partial cut can be counted.
    """
    c = ctx.canvas()
    c.clear("black")

    c.fill_rect(0, 0, c.width, 2, "red")
    c.fill_rect(0, c.height - 2, c.width, 2, "blue")

    # Ruler on both edges: a tick every 4 rows, brighter every 8.
    for y in range(0, c.height, 4):
        shade = "white" if y % 8 == 0 else "dim"
        c.fill_rect(0, y, 3 if y % 8 == 0 else 2, 1, shade)
        c.fill_rect(c.width - (3 if y % 8 == 0 else 2), y, 3 if y % 8 == 0 else 2, 1, shade)

    c.centered("RED=TOP", "red", "3x5", y=9)
    c.centered(f"{c.width}x{c.height} ALL ROWS", "white", "3x5", y=15)
    c.centered("BLUE=BOTTOM", "sky", "3x5", y=21)
    return c
