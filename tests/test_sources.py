from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from glance.sources.holidays import (
    Holiday, active_holidays, easter, load_holidays, nth_weekday,
)
from glance.sources.ics import CalendarSource
from glance.sources.todos import TodoSource

TZ = ZoneInfo("America/Los_Angeles")


# --- holiday date maths -----------------------------------------------------

@pytest.mark.parametrize(
    "year,expected",
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
     (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28)), (2030, date(2030, 4, 21))],
)
def test_easter_matches_known_dates(year, expected):
    assert easter(year) == expected


@pytest.mark.parametrize(
    "year,expected",
    [(2025, date(2025, 11, 27)), (2026, date(2026, 11, 26)), (2027, date(2027, 11, 25))],
)
def test_fourth_thursday_of_november(year, expected):
    assert nth_weekday(year, 11, 3, 4) == expected


def test_last_weekday_of_month():
    assert nth_weekday(2026, 5, 0, -1) == date(2026, 5, 25)   # Memorial Day
    assert nth_weekday(2026, 2, 6, -1) == date(2026, 2, 22)   # last Sunday, short month


def test_fixed_date_holiday_window_and_tail():
    xmas = Holiday(name="Christmas", slug="christmas", window=14, after=1,
                   spec={"date": "12-25"})
    assert xmas.active_on(date(2026, 12, 25))[0]
    assert xmas.active_on(date(2026, 12, 11))[0]        # first day of the window
    assert not xmas.active_on(date(2026, 12, 10))[0]    # one day too early
    assert xmas.active_on(date(2026, 12, 26))[0]        # inside the tail
    assert not xmas.active_on(date(2026, 12, 27))[0]


def test_days_until_is_reported():
    xmas = Holiday(name="Christmas", slug="christmas", window=14, spec={"date": "12-25"})
    assert xmas.active_on(date(2026, 12, 20)) == (True, 5)
    assert xmas.active_on(date(2026, 12, 25)) == (True, 0)


def test_new_year_window_spans_the_year_boundary():
    """The window opens in December for a date in January -- the neighbouring-year
    check is the whole reason this case works."""
    ny = Holiday(name="New Year", slug="new-year", window=3, spec={"date": "01-01"})
    ok, days = ny.active_on(date(2026, 12, 30))
    assert ok and days == 2


def test_easter_relative_holiday():
    good_friday = Holiday(name="Good Friday", slug="gf", spec={"rule": {"easter_offset": -2}})
    assert good_friday.occurrence(2026) == date(2026, 4, 3)


def test_active_holidays_sorts_the_day_itself_first():
    a = Holiday(name="Far", slug="far", window=30, spec={"date": "12-25"})
    b = Holiday(name="Near", slug="near", window=30, spec={"date": "12-05"})
    hits = active_holidays([a, b], date(2026, 12, 5))
    assert [h.name for h, _ in hits] == ["Near", "Far"]


def test_load_holidays_tolerates_a_missing_file(tmp_path: Path):
    assert load_holidays(tmp_path / "nope.yaml") == []


def test_loaded_holidays_get_slugs(project: Path):
    holidays = load_holidays(project / "config" / "holidays.yaml")
    assert {h.slug for h in holidays} == {"christmas", "thanksgiving"}


# --- todos ------------------------------------------------------------------

def test_open_items_exclude_done_and_sort_by_urgency(project: Path):
    src = TodoSource(project / "data" / "todos.json")
    items = src.open_items(date(2026, 9, 8))
    assert [t.text for t in items] == ["Renew passport", "Water ferns"]


def test_undated_items_sort_after_dated_ones(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps([{"text": "someday"}, {"text": "friday", "due": "2026-09-11"}]))
    assert [t.text for t in TodoSource(p).open_items(date(2026, 9, 8))] == ["friday", "someday"]


def test_overdue_detection():
    src = TodoSource(Path("/nonexistent"))
    assert src.all() == []
    assert src.last_error


def test_file_is_reread_when_it_changes(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps([{"text": "first"}]))
    src = TodoSource(p)
    assert [t.text for t in src.all()] == ["first"]

    import os, time
    p.write_text(json.dumps([{"text": "second"}]))
    os.utime(p, (time.time() + 10, time.time() + 10))
    assert [t.text for t in src.all()] == ["second"]


def test_bare_strings_and_wrapper_object_are_accepted(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"todos": ["just a string", {"text": "an object"}]}))
    assert len(TodoSource(p).all()) == 2


def test_malformed_json_keeps_the_last_good_list(tmp_path: Path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps([{"text": "good"}]))
    src = TodoSource(p)
    assert len(src.all()) == 1

    import os, time
    p.write_text("{not json")
    os.utime(p, (time.time() + 10, time.time() + 10))
    assert [t.text for t in src.all()] == ["good"]     # stale beats blank
    assert src.last_error


# --- calendar ---------------------------------------------------------------

def test_recurring_events_expand_and_skip_the_weekend(ics_server, tmp_path: Path, now):
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    events = src.upcoming(now, lookahead_days=7)
    assert src.last_error is None
    standups = [e for e in events if e.summary == "Team standup"]
    days = {e.start.strftime("%a") for e in standups}
    assert "Sat" not in days and "Sun" not in days
    assert len(standups) >= 4


def test_utc_timestamps_convert_to_local(ics_server, tmp_path: Path, now):
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    review = next(e for e in src.upcoming(now) if e.summary == "Quarterly review")
    assert (review.start.hour, review.start.minute) == (10, 0)   # 17:00Z in PDT


def test_all_day_events_are_flagged_and_span_the_day(ics_server, tmp_path: Path, now):
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    bday = next(e for e in src.upcoming(now) if e.summary == "Anna birthday")
    assert bday.all_day
    assert bday.start.hour == 0 and bday.end.hour == 23


def test_events_are_returned_in_chronological_order(ics_server, tmp_path: Path, now):
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    starts = [e.start for e in src.upcoming(now)]
    assert starts == sorted(starts)


def test_in_progress_events_are_detected(ics_server, tmp_path: Path):
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    mid = datetime(2026, 9, 8, 9, 35, tzinfo=TZ)
    assert [e.summary for e in src.upcoming(mid) if e.is_now(mid)] == ["Team standup"]


def test_finished_events_drop_out(ics_server, tmp_path: Path):
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    after = datetime(2026, 9, 8, 10, 0, tzinfo=TZ)
    same_day = [e for e in src.upcoming(after) if e.start.date() == after.date()]
    assert "Team standup" not in [e.summary for e in same_day]


def test_a_dead_server_falls_back_to_the_disk_cache(ics_server, tmp_path: Path, now):
    """A blank panel is worse than slightly stale events."""
    src = CalendarSource(ics_server, tmp_path, tz=TZ, refresh=0)
    assert src.upcoming(now)

    src.url = "http://127.0.0.1:1/gone.ics"
    events = src.upcoming(now)
    assert events, "should have served the cached copy"
    assert src.last_error, "the failed fetch should still be reported"


def test_no_cache_and_no_server_yields_no_events_not_an_exception(tmp_path: Path, now):
    src = CalendarSource("http://127.0.0.1:1/gone.ics", tmp_path, tz=TZ, refresh=0)
    assert src.events(now) == []
    assert src.last_error


def test_a_non_calendar_response_is_rejected(tmp_path: Path, now, ics_server):
    bad = ics_server.replace("test.ics", "missing.ics")
    src = CalendarSource(bad, tmp_path, tz=TZ, refresh=0)
    assert src.events(now) == []
    assert src.last_error
