"""Three columns of what is coming next.

192 divides into three 64px columns, which is exactly one physical LED module
each -- the layout lands on the hardware's own seams.

Days are packed greedily. A day fills its column; if it has more events than
fit, it spills into the next one and pushes the following day along. So the
best case is three days of a few events each, and the worst case is one busy
day occupying all three columns, which is the right thing to show when that is
what the day looks like.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .agenda import day_label
from .base import Param, RenderContext, register

ROWS_PER_COLUMN = 4
ROW_Y = (7, 13, 19, 25)
HEADER_Y = 0
RULE_Y = 5


def compact_time(when: datetime, all_day: bool, hour24: bool = False) -> str:
    """As short as it can be without becoming ambiguous.

    On the hour drops the minutes -- "9a" rather than "9:00a" -- which buys
    ten pixels of title on half the rows, and a 64px column has no pixels to
    spare.
    """
    if all_day:
        return "ALL"
    if hour24:
        return when.strftime("%H:%M") if when.minute else when.strftime("%H")
    hour = when.hour % 12 or 12
    suffix = "a" if when.hour < 12 else "p"
    return f"{hour}{suffix}" if when.minute == 0 else f"{hour}:{when.minute:02d}{suffix}"


def group_by_day(events) -> list[tuple[date, list]]:
    days: dict[date, list] = {}
    for event in events:
        days.setdefault(event.start.date(), []).append(event)
    return [(d, days[d]) for d in sorted(days)]


def plan(days: list[tuple[date, list]], columns: int,
         rows: int = ROWS_PER_COLUMN) -> list[dict[str, Any]]:
    """Assign days to columns, letting a busy day take more than one.

    Returns one entry per column: which day it belongs to, which slice of that
    day's events it carries, whether it continues a previous column, and how
    many events had to be dropped.
    """
    out: list[dict[str, Any]] = []
    used = 0
    for day, events in days:
        if used >= columns:
            break
        wanted = max(1, -(-len(events) // rows))          # ceil
        available = columns - used
        taken = min(wanted, available)
        for index in range(taken):
            chunk = events[index * rows:(index + 1) * rows]
            last = index == taken - 1
            dropped = len(events) - taken * rows if last else 0
            out.append({
                "day": day,
                "events": chunk,
                "continued": index > 0,
                "dropped": max(0, dropped),
            })
        used += taken
    return out


def _events(ctx: RenderContext, params: dict[str, Any]):
    window = int(params.get("lookahead_days", 14))
    if ctx.calendars:
        events = ctx.calendars.upcoming(ctx.now, names=params.get("calendar"),
                                        lookahead_days=window)
    elif ctx.calendar is not None:
        events = ctx.calendar.upcoming(ctx.now, lookahead_days=window)
    else:
        return []

    # `from_days` skips whole calendar days rather than whole event-groups.
    # Skipping groups would be unpredictable: a single busy day can fill every
    # column, so "skip 3 days of events" could silently skip past a week.
    skip = int(params.get("from_days", 0))
    if skip > 0:
        first = ctx.today + timedelta(days=skip)
        events = [e for e in events if e.start.date() >= first]
    return events


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    return bool(params.get("always")) or bool(_events(ctx, params))


@register("columns", available=_available,
          description="Three columns of upcoming events, packed by day",
          params=[
              Param("calendar", "select", None, options="@calendars",
                    help="Which feed, or blank for all"),
              Param("columns", "number", 3, minimum=1, maximum=6),
              Param("skip_columns", "number", 0, minimum=0, maximum=9,
                    help="Start this many columns in. Pair two panels with 0 "
                         "and 3 and they run continuously, whatever the packing."),
              Param("days", "number", None, minimum=1, maximum=12,
                    help="Distinct days to consider; defaults to the column count"),
              Param("hour24", "bool", False),
              Param("accent", "color", "amber", options="@colors"),
              Param("from_days", "number", 0, minimum=0, maximum=30,
                    help="Start this many days ahead. 0 is today; 3 skips the "
                         "near term a companion panel already covers."),
              Param("lookahead_days", "number", 14, minimum=1, maximum=90),
          ])
def render_columns(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small = get_font("3x5")
    accent = params.get("accent", "amber")
    hour24 = bool(params.get("hour24", False))

    count = max(1, int(params.get("columns", 3)))
    width = c.width // count

    # Skipping *columns* rather than days is what makes two panels continuous:
    # one shows columns 1-3 and the other 4-6, so they never overlap and never
    # leave a gap, however the days happen to pack. Skipping calendar days
    # cannot do that -- whether the near view spilled is exactly what decides
    # where the far view should start.
    skip = max(0, int(params.get("skip_columns", 0)))
    total = skip + count

    events = _events(ctx, params)
    if not events:
        ahead = int(params.get("from_days", 0))
        message = (f"nothing after {ahead} days" if ahead else "nothing scheduled")
        c.centered(str(params.get("empty", message)), "dim", small,
                   max_width=c.width - 4)
        return c

    # Each column can be a different day, so consider at least as many days as
    # there are columns to fill.
    day_limit = max(1, int(params.get("days", total)))
    days = group_by_day(events)[:day_limit]
    layout = plan(days, total)[skip:]

    if not layout:
        c.centered(str(params.get("empty", "nothing further")), "dim", small,
                   max_width=c.width - 4)
        return c

    for index, column in enumerate(layout):
        x = index * width
        inner = width - 3

        if index:
            c.vline(x - 1, 2, c.height - 4, dim(accent, 0.25))

        label = day_label(column["events"][0].start, ctx.now) if column["events"] else ""
        if column["continued"]:
            # A continuation is the same day, said quietly so the eye does not
            # read it as a new one.
            c.text(x + 1, HEADER_Y, label, dim(accent, 0.4), small, max_width=inner)
        else:
            c.text(x + 1, HEADER_Y, label, accent, small, max_width=inner)
        c.hline(x + 1, RULE_Y, inner, dim(accent, 0.3))

        # The "+N" badge shares the last row with a title, so its width has to
        # come out of that title's budget -- otherwise it simply draws over it.
        badge = ""
        if column["dropped"] > 0 and len(column["events"]) >= ROWS_PER_COLUMN:
            badge = f"+{column['dropped']}"
        badge_w = small.measure(badge) + 3 if badge else 0

        shown = column["events"][:ROWS_PER_COLUMN]
        for row, event in enumerate(shown):
            y = ROW_Y[row]
            stamp = compact_time(event.start, event.all_day, hour24)
            colour = "green" if event.is_now(ctx.now) else (event.style.color or accent)
            c.text(x + 1, y, stamp, colour, small)
            title_x = x + 1 + small.measure(stamp) + 3
            reserve = badge_w if (badge and row == len(shown) - 1) else 0
            c.text(title_x, y, event.summary,
                   dim("white", 0.55) if event.style.dim else "white",
                   small, max_width=x + width - title_x - 2 - reserve)

        if badge:
            # Say how many did not fit rather than silently dropping the day.
            c.text(x + width - 2, ROW_Y[-1], badge, dim(accent, 0.75), small, "right")
    return c
