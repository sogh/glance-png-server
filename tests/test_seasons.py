"""When the seasons actually start, and the countdown that uses it."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from glance.scenes import REGISTRY
from glance.seasons import (POINTS, days_until, next_start, point_at, resolve,
                            starts_at)

TZ = ZoneInfo("America/Los_Angeles")

# Published instants, US Naval Observatory / timeanddate, in UTC.
KNOWN = {
    (2024, "march"): "2024-03-20 03:06", (2024, "june"): "2024-06-20 20:51",
    (2024, "september"): "2024-09-22 12:44", (2024, "december"): "2024-12-21 09:20",
    (2025, "march"): "2025-03-20 09:01", (2025, "june"): "2025-06-21 02:42",
    (2025, "september"): "2025-09-22 18:19", (2025, "december"): "2025-12-21 15:03",
    (2026, "september"): "2026-09-23 00:05", (2026, "december"): "2026-12-21 20:50",
    (2000, "march"): "2000-03-20 07:35", (2030, "june"): "2030-06-21 07:31",
}


# --- the astronomy ----------------------------------------------------------

@pytest.mark.parametrize("key,expected", sorted(KNOWN.items()))
def test_equinoxes_and_solstices_match_published_values(key, expected):
    """Within a couple of minutes across thirty years. Rather more precision
    than a day count needs, but the alternative is a table that runs out."""
    year, point = key
    want = datetime.strptime(expected, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    drift = abs((point_at(year, point) - want).total_seconds()) / 60
    assert drift <= 3, f"{year} {point}: off by {drift:.1f} minutes"


def test_the_equinox_moves_between_years():
    """Why this is computed and not written down. In UTC the September equinox
    is the 22nd or the 23rd depending on the year."""
    days = {point_at(y, "september").astimezone(timezone.utc).day
            for y in range(2020, 2041)}
    assert days == {22, 23}


def test_which_local_date_that_is_depends_on_the_zone():
    """The trap a hardcoded date sets. Over 2020-2040 the September equinox is
    always the 22nd in Los Angeles, but lands on both the 22nd and the 23rd in
    Berlin -- so "09-22" is right where it was written and wrong elsewhere."""
    def days(zone):
        tz = ZoneInfo(zone)
        return {point_at(y, "september").astimezone(tz).day for y in range(2020, 2041)}

    assert days("America/Los_Angeles") == {22}
    assert days("Europe/Berlin") == {22, 23}
    assert days("Pacific/Auckland") == {22, 23}


def test_an_unknown_point_is_refused():
    with pytest.raises(ValueError):
        point_at(2026, "octember")


# --- naming -----------------------------------------------------------------

def test_fall_and_autumn_are_the_same_thing():
    assert resolve("fall") == resolve("autumn") == "september"


def test_the_southern_hemisphere_gets_the_opposite_season():
    assert resolve("autumn", "north") == "september"
    assert resolve("autumn", "south") == "march"
    assert resolve("summer", "south") == "december"


def test_a_month_point_passes_through_unchanged():
    for point in POINTS:
        assert resolve(point) == point


def test_an_unknown_season_is_refused():
    with pytest.raises(ValueError):
        resolve("harvest")


# --- counting ---------------------------------------------------------------

def test_the_local_date_can_differ_from_the_utc_one():
    """The 2026 September equinox is 00:05 UTC on the 23rd, which is the 22nd
    in Seattle. Counting in UTC would be a day out."""
    assert point_at(2026, "september").astimezone(timezone.utc).day == 23
    assert starts_at(2026, "autumn", tz=TZ).day == 22


def test_it_rolls_into_next_year_once_the_season_has_begun():
    """A countdown pinned to a fixed date spends eleven months counting up."""
    after = datetime(2026, 10, 1, tzinfo=TZ)
    assert next_start(after, "autumn").year == 2027


def test_days_are_counted_as_calendar_days_not_24_hour_blocks():
    """If autumn begins tomorrow at any hour the answer is 1, not 0."""
    start = starts_at(2026, "autumn", tz=TZ)
    late = start.replace(hour=1) - timedelta(days=1)     # the小 hours before
    assert days_until(late, "autumn") == 1
    assert days_until(start.replace(hour=0, minute=1), "autumn") == 0


def test_meteorological_seasons_start_on_the_first():
    start = next_start(datetime(2026, 7, 1, tzinfo=TZ), "autumn", meteorological=True)
    assert (start.month, start.day) == (9, 1)


# --- the scene --------------------------------------------------------------

NOW = datetime(2026, 9, 16, 12, 0, tzinfo=TZ)


def target(app, params):
    from glance.scenes.basic import countdown_target
    return countdown_target(app.context(NOW), params)


def test_counting_to_a_season(app):
    days, label = target(app, {"season": "fall"})
    assert days == 6                    # equinox is 2026-09-22 locally
    assert label == "FALL"


def test_a_month_day_repeats_every_year(app):
    """A birthday countdown should not expire."""
    assert target(app, {"date": "12-25"})[0] == 100
    # One that has already gone by this year points at next year's.
    assert target(app, {"date": "01-01"})[0] > 100


def test_a_full_date_is_a_one_off(app):
    assert target(app, {"date": "2026-09-20"})[0] == 4
    assert target(app, {"date": "2026-09-10"})[0] == -6      # counts upward after


def test_nothing_configured_is_reported_not_guessed(app):
    assert target(app, {}) is None
    assert target(app, {"date": "not-a-date"}) is None
    assert target(app, {"season": "harvest"}) is None


def test_a_countdown_can_schedule_itself(app):
    """Otherwise a countdown to autumn spends nine months of the year taking a
    slot to say "271"."""
    scene = REGISTRY["countdown"]
    ctx = app.context(NOW)
    assert scene.available(ctx, {"season": "fall", "within": 30})
    assert not scene.available(ctx, {"season": "fall", "within": 3})
    assert scene.available(ctx, {"season": "fall", "within": 3, "always": True})
    assert scene.available(ctx, {"season": "fall"})          # 0 means always


def test_it_draws_something_for_every_form(app):
    scene = REGISTRY["countdown"]
    ctx = app.context(NOW, brightness=1.0)
    for params in ({"season": "fall"}, {"date": "12-25"}, {"date": "2026-09-16"},
                   {"season": "summer", "hemisphere": "south"}, {}):
        canvas = scene.render(ctx, params)
        assert canvas.image.get_flattened_data().count((0, 0, 0)) < 192 * 32
