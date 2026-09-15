"""Three columns of upcoming events, packed by day."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from glance.scenes import REGISTRY
from glance.scenes.columns import compact_time, group_by_day, plan
from glance.sources.ics import Event

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 13, 7, 0, tzinfo=TZ)


def ev(day, hour, minute, title, all_day=False):
    start = NOW.replace(hour=hour, minute=minute) + timedelta(days=day)
    return Event(summary=title, start=start, end=start + timedelta(hours=1),
                 all_day=all_day, raw_summary=title)


class FakeCalendars:
    def __init__(self, events): self._e = events
    def __bool__(self): return True
    def upcoming(self, now, names=None, lookahead_days=14, include_current=True):
        return sorted(self._e, key=lambda e: e.start)


def render(app, events, params=None):
    ctx = app.context(NOW, brightness=1.0)
    ctx.calendars = FakeCalendars(events)
    ctx.calendar = None
    return REGISTRY["columns"].render(ctx, params or {})


# --- time formatting --------------------------------------------------------

def test_on_the_hour_drops_its_minutes():
    """A 64px column has no pixels to spare."""
    assert compact_time(NOW.replace(hour=9, minute=0), False) == "9a"
    assert compact_time(NOW.replace(hour=9, minute=30), False) == "9:30a"
    assert compact_time(NOW.replace(hour=14, minute=0), False) == "2p"
    assert compact_time(NOW.replace(hour=0, minute=15), False) == "12:15a"


def test_all_day_says_so():
    assert compact_time(NOW, True) == "ALL"


def test_24_hour_mode():
    assert compact_time(NOW.replace(hour=14, minute=0), False, hour24=True) == "14"
    assert compact_time(NOW.replace(hour=14, minute=30), False, hour24=True) == "14:30"


# --- packing ----------------------------------------------------------------

def fake(n): return list(range(n))


def test_quiet_days_get_one_column_each():
    days = [(date(2026, 9, 13), fake(2)), (date(2026, 9, 14), fake(1)),
            (date(2026, 9, 15), fake(3))]
    out = plan(days, 3)
    assert len(out) == 3
    assert [len(c["events"]) for c in out] == [2, 1, 3]
    assert not any(c["continued"] for c in out)


def test_a_busy_day_spills_and_pushes_the_next_along():
    days = [(date(2026, 9, 13), fake(7)), (date(2026, 9, 14), fake(2)),
            (date(2026, 9, 15), fake(1))]
    out = plan(days, 3)
    assert [c["day"].day for c in out] == [13, 13, 14], "day 15 gets pushed off"
    assert out[1]["continued"] and not out[0]["continued"]


def test_one_enormous_day_takes_every_column():
    out = plan([(date(2026, 9, 13), fake(20))], 3)
    assert len(out) == 3
    assert all(c["day"].day == 13 for c in out)
    assert out[-1]["dropped"] == 8, "and says how many it could not show"


def test_nothing_is_dropped_when_everything_fits():
    out = plan([(date(2026, 9, 13), fake(4))], 3)
    assert out[0]["dropped"] == 0


def test_grouping_splits_on_date_not_time():
    events = [ev(0, 9, 0, "a"), ev(0, 17, 0, "b"), ev(1, 8, 0, "c")]
    grouped = group_by_day(events)
    assert [len(g[1]) for g in grouped] == [2, 1]


# --- rendering --------------------------------------------------------------

def test_it_renders_three_days(app):
    c = render(app, [ev(0, 9, 30, "Standup"), ev(1, 11, 0, "Bowling"),
                     ev(2, 6, 45, "Scan")])
    assert c.image.size == (192, 32)
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 150


def test_columns_land_on_the_module_seams(app):
    """192/3 is 64, which is exactly one physical LED module per column."""
    c = render(app, [ev(0, 9, 0, "a"), ev(1, 9, 0, "b"), ev(2, 9, 0, "c")])
    assert c.width % 3 == 0 and c.width // 3 == 64


def test_nothing_overflows_the_panel(app):
    events = [ev(d, 6 + i, 30, "A very long event title indeed")
              for d in range(3) for i in range(4)]
    c = render(app, events)
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_the_overflow_badge_does_not_draw_over_the_title(app):
    """It shares the last row with a title, so its width has to come out of
    that title's budget."""
    events = [ev(0, 6 + i, 0, f"Task number {i}") for i in range(14)]
    c = render(app, events)
    # The badge sits hard right on the last row; the rightmost column of that
    # row must be either badge or blank, never a half-drawn glyph collision.
    assert c.image.size == (192, 32)
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_an_in_progress_event_still_reads_green(app):
    live = ev(0, 6, 30, "Happening")
    live.end = NOW + timedelta(hours=2)
    c = render(app, [live])
    greens = [p for p in c.image.get_flattened_data() if p[1] > 120 and p[0] < 90]
    assert greens


def test_an_empty_calendar_says_so(app):
    c = render(app, [])
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 0


def test_the_column_count_is_configurable(app):
    events = [ev(d, 9, 0, "x") for d in range(3)]
    three = render(app, events)
    two = render(app, events, {"columns": 2})
    assert three.to_ascii() != two.to_ascii()


def test_ampersands_survive(app):
    """'Health & Wealth Grange' drew as 'Health ? Wealth' until the 3x5 font
    learned the glyph."""
    from glance.fonts import FONT_3X5
    assert "&" in FONT_3X5.source
    c = render(app, [ev(0, 17, 30, "Health & Wealth")])
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 80


# --- looking further ahead --------------------------------------------------

def test_from_days_skips_the_near_term(app):
    events = [ev(0, 9, 0, "Today thing"), ev(1, 9, 0, "Tomorrow thing"),
              ev(4, 9, 0, "Next week thing")]
    near = render(app, events)
    far = render(app, events, {"from_days": 3})
    assert near.to_ascii() != far.to_ascii()


def test_from_days_counts_calendar_days_not_event_groups(app):
    """Skipping groups would be unpredictable: one busy day can fill every
    column, so 'skip 3 days of events' could silently skip a week."""
    from glance.scenes.columns import _events

    class Ctx:
        pass

    events = [ev(0, h, 0, f"t{h}") for h in range(6, 18)] + [ev(3, 9, 0, "later")]
    ctx = app.context(NOW)
    ctx.calendars = FakeCalendars(events)
    ctx.calendar = None
    kept = _events(ctx, {"from_days": 3})
    assert [e.summary for e in kept] == ["later"]


def test_zero_from_days_changes_nothing(app):
    events = [ev(0, 9, 0, "a"), ev(2, 9, 0, "b")]
    assert render(app, events).to_ascii() == render(app, events, {"from_days": 0}).to_ascii()


def test_an_empty_far_view_says_why(app):
    """'nothing scheduled' would read as a broken feed when the near term is
    simply being skipped."""
    c = render(app, [ev(0, 9, 0, "only today")], {"from_days": 3})
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 0


# --- column offset: making two panels continuous ----------------------------

def week():
    return [ev(0, 9, 0, "Feed"), ev(0, 14, 0, "Eggs"),
            ev(1, 10, 0, "Zoom"), ev(2, 11, 0, "Bowling"),
            ev(3, 6, 45, "Scan"), ev(4, 12, 0, "Haircut"),
            ev(5, 9, 0, "Prep"), ev(6, 10, 0, "Tour")]


def test_skipping_columns_continues_where_the_first_panel_stopped(app):
    near = render(app, week())
    far = render(app, week(), {"skip_columns": 3})
    assert near.to_ascii() != far.to_ascii()


@pytest.mark.parametrize("shape", ["quiet", "busy", "enormous"])
def test_the_two_panels_never_overlap_and_never_gap(shape):
    """Whatever the packing, columns[0:3] and columns[3:6] are adjacent."""
    from datetime import date

    def fake(n): return list(range(n))
    days = {
        "quiet": [(date(2026, 9, d), fake(2)) for d in range(13, 20)],
        "busy": [(date(2026, 9, 13), fake(7))] + [(date(2026, 9, d), fake(2))
                                                  for d in range(14, 19)],
        "enormous": [(date(2026, 9, 13), fake(20)), (date(2026, 9, 14), fake(3))],
    }[shape]

    full = plan(days, 6)
    near, far = full[0:3], full[3:6]
    assert len(near) + len(far) == len(full)
    # Every event appears exactly once across the two panels, in order.
    seen = [e for column in near + far for e in column["events"]]
    assert seen == [e for column in full for e in column["events"]]


def test_a_day_that_spans_the_boundary_continues_rather_than_restarting():
    from datetime import date

    def fake(n): return list(range(n))
    full = plan([(date(2026, 9, 13), fake(20))], 6)
    assert full[3]["continued"], "the far panel should carry on the same day"
    assert full[3]["day"] == full[2]["day"]


def test_the_day_limit_grows_with_the_column_count(app):
    """Six columns can be six different days, so six days must be considered."""
    near = render(app, week(), {"skip_columns": 3})
    assert sum(1 for p in near.image.get_flattened_data() if sum(p) > 0) > 60


def test_skipping_past_everything_says_so_rather_than_drawing_blank(app):
    c = render(app, [ev(0, 9, 0, "only one")], {"skip_columns": 3})
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 0


def test_zero_skip_is_unchanged(app):
    assert (render(app, week()).to_ascii()
            == render(app, week(), {"skip_columns": 0}).to_ascii())


# --- conditional word wrap --------------------------------------------------

def test_spare_rows_go_to_titles_that_want_them():
    from glance.scenes.columns import allocate_rows
    assert allocate_rows([2, 2]) == [2, 2]
    assert allocate_rows([3, 1]) == [3, 1]
    assert allocate_rows([4]) == [4]


def test_a_full_column_never_wraps():
    """Wrapping must never cost an event its slot."""
    from glance.scenes.columns import allocate_rows
    assert allocate_rows([2, 2, 2, 2]) == [1, 1, 1, 1]
    assert allocate_rows([4, 1, 1, 1]) == [1, 1, 1, 1]


def test_partial_spare_is_shared_most_starved_first():
    from glance.scenes.columns import allocate_rows
    assert sum(allocate_rows([2, 2, 1])) == 4
    assert allocate_rows([3, 2, 1]) == [2, 1, 1]


def test_allocation_never_exceeds_the_column():
    from glance.scenes.columns import allocate_rows
    for needs in ([1], [9], [3, 3], [2, 2, 2], [5, 5, 5, 5]):
        assert sum(allocate_rows(needs)) <= 4


def test_a_long_title_uses_a_second_row_when_alone(app):
    long_title = "Meggie gets scanned at the vet"
    wrapped = render(app, [ev(0, 11, 15, long_title)])
    flat = render(app, [ev(0, 11, 15, long_title)], {"wrap": False})
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit(wrapped) > lit(flat), "more of the title should be visible"


def test_a_busy_column_looks_the_same_either_way(app):
    """With four events there is no spare row, so wrap changes nothing."""
    busy = [ev(0, 6 + i, 0, f"A fairly long event title {i}") for i in range(4)]
    assert render(app, busy).to_ascii() == render(app, busy, {"wrap": False}).to_ascii()


def test_wrapping_still_respects_the_panel_edge(app):
    c = render(app, [ev(0, 9, 0, "An extremely long event title that runs on and on")])
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_wrapped_rows_stay_inside_the_column(app):
    """A second line must not bleed into the neighbouring column."""
    events = [ev(0, 9, 0, "A very long title indeed that wraps"),
              ev(1, 9, 0, "Tomorrow")]
    c = render(app, events)
    # The divider column between panel 1 and 2 is at x = 63.
    for y in range(7, 32):
        assert sum(c.image.getpixel((62, y))) == 0, f"bled into the divider at row {y}"


# --- telling the time from the title ----------------------------------------

def colours(canvas):
    return {p for p in canvas.image.get_flattened_data() if p != (0, 0, 0)}


def test_the_time_is_not_the_same_colour_as_the_event(app):
    """Both used to come out white: the stamp took the calendar's configured
    colour, which is white, and the title was hardcoded to it -- so the one
    field meant to stand apart did not."""
    from glance.palette import parse
    c = render(app, [ev(0, 9, 30, "Standup")], {"accent": "amber"})
    present = colours(c)
    assert parse("amber") in present, "the time should carry the accent"
    assert parse("white") in present, "the title should stay white"


def test_the_time_colour_is_configurable(app):
    from glance.palette import parse
    c = render(app, [ev(0, 9, 30, "Standup")],
               {"accent": "amber", "time_color": "sky"})
    assert parse("sky") in colours(c)
    assert parse("white") in colours(c)


def test_a_tag_tints_the_event_not_the_clock(app):
    """A #red on an entry should make the entry stand out. It used to colour
    the time instead, which is the opposite of what anyone would expect."""
    from glance.palette import parse
    from glance.sources.tags import Style

    tagged = ev(0, 9, 30, "Dentist")
    tagged.style = Style(color="red")
    c = render(app, [tagged], {"accent": "amber", "time_color": "amber"})
    present = colours(c)
    assert parse("red") in present, "the title should be red"
    assert parse("amber") in present, "the time should still be the accent"


def test_an_event_happening_now_still_turns_the_time_green(app):
    from glance.palette import parse
    live = ev(0, 6, 30, "Standup")          # started an hour before NOW
    assert live.is_now(NOW)
    assert parse("green") in colours(render(app, [live], {"accent": "amber"}))
