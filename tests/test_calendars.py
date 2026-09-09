"""Multiple named calendars, and styling carried through a real ICS feed."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from glance.sources.calendars import CalendarSet
from glance.sources.tags import Style

TZ = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def two_calendars(ics_server, tagged_ics_server, tmp_path: Path) -> CalendarSet:
    return CalendarSet(
        {
            "agenda": {"url": ics_server, "refresh": 0, "color": "white", "accent": "amber"},
            "reminders": {"url": tagged_ics_server, "refresh": 0, "accent": "sky"},
            "notconfigured": {"url": ""},
        },
        cache_dir=tmp_path,
        tz=TZ,
    )


def test_only_configured_calendars_are_loaded(two_calendars):
    assert set(two_calendars.names) == {"agenda", "reminders"}
    assert "notconfigured" not in two_calendars


def test_selecting_one_calendar(two_calendars, now):
    events = two_calendars.upcoming(now, names="reminders")
    assert events
    assert {e.calendar for e in events} == {"reminders"}


def test_selecting_several_by_comma(two_calendars, now):
    events = two_calendars.upcoming(now, names="agenda,reminders")
    assert {e.calendar for e in events} == {"agenda", "reminders"}


def test_omitting_the_name_merges_everything_in_time_order(two_calendars, now):
    events = two_calendars.upcoming(now)
    assert {e.calendar for e in events} == {"agenda", "reminders"}
    assert [e.start for e in events] == sorted(e.start for e in events)


def test_an_unknown_calendar_name_yields_nothing(two_calendars, now):
    assert two_calendars.upcoming(now, names="nope") == []


# --- styling through a real feed -------------------------------------------

def test_a_title_tag_survives_the_ics_round_trip(two_calendars, now):
    ev = next(e for e in two_calendars.upcoming(now, "reminders")
              if e.summary.startswith("Call the plumber"))
    assert ev.summary == "Call the plumber", "the tag must be stripped"
    assert ev.raw_summary == "Call the plumber #red"
    assert ev.style.color == "red"


def test_description_styling_survives(two_calendars, now):
    ev = next(e for e in two_calendars.upcoming(now, "reminders")
              if e.summary == "Grange meeting")
    assert ev.style.color == "green"
    assert ev.style.style == "hero"


def test_hidden_entries_never_reach_the_panel(two_calendars, now):
    titles = [e.summary for e in two_calendars.upcoming(now, "reminders")]
    assert not any("Not for the panel" in t for t in titles)


def test_an_unknown_hashtag_is_left_in_the_title(two_calendars, now):
    ev = next(e for e in two_calendars.upcoming(now, "reminders")
              if "parcel" in e.summary)
    assert ev.summary == "Pick up the #1 parcel"


def test_calendar_defaults_fill_in_what_the_entry_did_not_set(two_calendars, now):
    plain = next(e for e in two_calendars.upcoming(now, "reminders")
                 if "parcel" in e.summary)
    assert plain.style.accent == "sky", "should inherit the calendar's accent"

    tagged = next(e for e in two_calendars.upcoming(now, "reminders")
                  if e.summary == "Call the plumber")
    assert tagged.style.color == "red", "entry colour beats the calendar default"
    assert tagged.style.accent == "sky", "but the accent still comes from the calendar"


def test_events_know_which_calendar_they_came_from(two_calendars, now):
    for e in two_calendars.upcoming(now):
        assert e.calendar in ("agenda", "reminders")


def test_status_reports_each_feed(two_calendars, now):
    st = two_calendars.status(now)
    assert set(st) == {"agenda", "reminders"}
    assert all(v["last_error"] is None for v in st.values())
