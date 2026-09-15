"""Calendar scenes driven by the ICS feed."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register

CHIP_WIDTH = 50


def fmt_time(dt: datetime, hour24: bool = False) -> tuple[str, str]:
    """Split a time into (digits, meridiem) so the two can be sized separately."""
    if hour24:
        return dt.strftime("%H:%M"), ""
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d}", "AM" if dt.hour < 12 else "PM"


def day_label(dt: datetime, now: datetime) -> str:
    delta = (dt.date() - now.date()).days
    if delta == 0:
        return "TODAY"
    if delta == 1:
        return "TMRW"
    if 2 <= delta <= 6:
        return dt.strftime("%a").upper()
    return dt.strftime("%d %b").upper().lstrip("0")


def relative_label(dt: datetime, now: datetime) -> str:
    minutes = int((dt - now).total_seconds() // 60)
    if minutes < 60:
        return f"IN {max(minutes, 0)}M"
    if minutes < 60 * 24:
        return f"IN {minutes // 60}H"
    return f"IN {minutes // (60 * 24)}D"


def _events(ctx: RenderContext, params: dict[str, Any]):
    days = int(params.get("lookahead_days", ctx.settings.ics_lookahead_days))
    # `calendar: reminders` or `calendar: "agenda,events"` selects feeds;
    # omitting it merges them all.
    if ctx.calendars:
        events = ctx.calendars.upcoming(
            ctx.now, names=params.get("calendar"), lookahead_days=days
        )
    elif ctx.calendar is not None:
        events = ctx.calendar.upcoming(ctx.now, lookahead_days=days)
    else:
        return []
    # `today: true` turns this from "what is next" into "what is left today",
    # which is a different and equally useful panel.
    if params.get("today"):
        events = [e for e in events if e.start.date() == ctx.today]
    return events


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    # `always: true` keeps the entry in rotation with an empty calendar, so it
    # can say "nothing scheduled" rather than dropping out of the slot.
    if params.get("always"):
        return True
    return bool(_events(ctx, params))


AGENDA_PARAMS = [
    Param("calendar", "select", None, options="@calendars",
          help="Which feed, or blank for all. Comma-separate for several."),
    Param("count", "number", 1, minimum=1, maximum=3,
          help="1 draws the hero layout; 2-3 stack as a list"),
    Param("today", "bool", False, help="Only what is left today"),
    Param("hour24", "bool", False, help="24-hour clock"),
    Param("lookahead_days", "number", 14, minimum=1, maximum=90),
    Param("accent", "color", "amber", options="@colors"),
    Param("time_color", "color", None, options="@colors",
          help="The time, drawn apart from the title; defaults to the accent"),
    Param("location", "bool", True, help="Show the location under the title"),
    Param("empty", "text", None, help="What to say when there is nothing"),
]


@register("agenda", available=_available, description="Next calendar event(s)",
          params=AGENDA_PARAMS)
def render_agenda(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    events = _events(ctx, params)
    count = int(params.get("count", 1))
    hour24 = bool(params.get("hour24", False))
    accent = params.get("accent", "amber")

    c = ctx.canvas()
    c.clear("black")
    if not events:
        c.centered(str(params.get("empty", "nothing today" if params.get("today")
                                  else "nothing scheduled")), "dim", "3x5")
        return c

    if count > 1:
        return _render_list(c, ctx, events[:count], hour24, accent,
                            params.get("time_color") or accent)
    return _render_hero(c, ctx, events[0], hour24, accent, params)


def _render_hero(c: Canvas, ctx: RenderContext, ev, hour24: bool, accent: str,
                 params: dict[str, Any]) -> Canvas:
    """One event: a time chip on the left, title filling the rest of the strip."""
    # An all-day event is technically "in progress" from midnight, but a NOW
    # chip counting down to 23:59 is worse than useless -- it reads as 11:59
    # in the morning once the meridiem is dropped. All-day entries always get
    # the ALL DAY chip.
    happening = ev.is_now(ctx.now) and not ev.all_day
    accent = ev.style.color or accent          # a #tag on the entry wins
    chip = "forest" if happening else accent
    c.fill_rect(0, 0, CHIP_WIDTH, c.height, dim(chip, 0.16))
    c.vline(CHIP_WIDTH, 0, c.height, dim(chip, 0.5))
    mid = CHIP_WIDTH // 2

    if happening:
        end_digits, end_mer = fmt_time(ev.end, hour24)
        # Keep a compact meridiem: "TIL 3:00" is ambiguous, "TIL 3:00P" is not.
        until = f"TIL {end_digits}" + (end_mer[0] if end_mer else "")
        c.text(mid, 7, "NOW", "green", "5x7", "center", CHIP_WIDTH - 2)
        c.text(mid, 18, until, dim("green", 0.8), "3x5", "center", CHIP_WIDTH - 2)
    elif ev.all_day:
        c.text(mid, 8, "ALL", accent, "5x7", "center", CHIP_WIDTH - 2)
        c.text(mid, 17, "DAY", accent, "5x7", "center", CHIP_WIDTH - 2)
        c.text(mid, 26, day_label(ev.start, ctx.now), dim(accent, 0.7), "3x5",
               "center", CHIP_WIDTH - 2)
    else:
        digits, meridiem = fmt_time(ev.start, hour24)
        # Three stacked lines: the time, then AM/PM (24h mode has none, so the
        # day moves up), then the day or a "starts in" countdown.
        second = meridiem or day_label(ev.start, ctx.now)
        third = day_label(ev.start, ctx.now) if meridiem else relative_label(ev.start, ctx.now)
        if second == third:
            third = relative_label(ev.start, ctx.now)
        c.text(mid, 5, digits, accent, "5x7", "center", CHIP_WIDTH - 2)
        c.text(mid, 15, second, dim(accent, 0.8), "3x5", "center", CHIP_WIDTH - 2)
        c.text(mid, 23, third, dim(accent, 0.6), "3x5", "center", CHIP_WIDTH - 2)

    # Title: two lines of 5x7 if it fits, otherwise three lines of 3x5.
    left = CHIP_WIDTH + 4
    avail = c.width - left - 2
    font = get_font("5x7")
    lines = font.wrap(ev.summary, avail)
    if len(lines) > 2:
        font = get_font("3x5")
        lines = font.wrap(ev.summary, avail)[:3]

    show_loc = bool(params.get("location", True)) and ev.location and len(lines) <= 2
    loc_h = get_font("3x5").height + 3 if show_loc else 0
    block = len(lines) * (font.height + 2) - 2
    top = max(1, (c.height - block - loc_h) // 2)
    c.text_block(left, top, lines, "white", font, leading=2)
    if show_loc:
        c.text(left, top + block + 3, ev.location, "grey", "3x5", max_width=avail)
    return c


def _render_list(c: Canvas, ctx: RenderContext, events, hour24: bool, accent: str,
                 time_colour: str | None = None) -> Canvas:
    """Two or three events stacked, time column on the left.

    Rows that are not today get a right-hand day badge. Without it a recurring
    9:30 standup renders identically on three consecutive lines, which reads as
    a bug rather than as three days of the same meeting.
    """
    time_colour = time_colour or accent
    rows = min(len(events), 3)
    step = 10 if rows >= 3 else 12
    top = (c.height - (rows * step - (step - 7))) // 2
    time_col = 38
    small = get_font("3x5")

    for i, ev in enumerate(events[:rows]):
        y = top + i * step
        if ev.all_day:
            label = "ALL"
        else:
            digits, meridiem = fmt_time(ev.start, hour24)
            label = digits if hour24 else f"{digits}{meridiem[0].lower()}"

        # The time carries its own colour, apart from the title -- see the
        # note in columns.py; both used to come out white.
        stamp_colour = "green" if ev.is_now(ctx.now) else time_colour
        c.text(1, y, label, stamp_colour, "5x7", max_width=time_col - 3)

        badge = "" if ev.start.date() == ctx.today else day_label(ev.start, ctx.now)
        badge_w = small.measure(badge) + 4 if badge else 0
        title_color = (dim("white", 0.55) if ev.style.dim
                       else ev.style.color or "white")
        c.text(time_col, y, ev.summary, title_color, "5x7",
               max_width=c.width - time_col - 2 - badge_w)
        if badge:
            c.text(c.width - 1, y + 1, badge, dim(accent, 0.65), small, "right")
    return c


def _today_defaults(params: dict[str, Any]) -> dict[str, Any]:
    """`today-agenda` is `agenda` with today-only defaults, still overridable."""
    merged = {"today": True, "count": 3, "always": True}
    merged.update(params)
    return merged


@register("today-agenda", available=lambda c, p: _available(c, _today_defaults(p)),
          description="What is left on today's calendar", params=AGENDA_PARAMS)
def render_today(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    return render_agenda(ctx, _today_defaults(params))
