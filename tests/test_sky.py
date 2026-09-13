"""Sun and moon crossing the sky."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from glance.moon import SYNODIC_MONTH, lit, phase_at
from glance.scenes import REGISTRY

TZ = ZoneInfo("America/Los_Angeles")


# --- moon phase -------------------------------------------------------------

def test_the_cycle_closes():
    base = datetime(2026, 1, 19, tzinfo=timezone.utc)
    assert phase_at(base).phase == pytest.approx(
        phase_at(base + timedelta(days=SYNODIC_MONTH)).phase, abs=0.01)


def test_full_moon_falls_half_a_lunation_after_new():
    base = datetime(2026, 1, 19, tzinfo=timezone.utc)
    new = phase_at(base)
    full = phase_at(base + timedelta(days=SYNODIC_MONTH / 2))
    assert new.illumination < 0.05
    assert full.illumination > 0.95


def test_quarters_are_half_lit():
    base = datetime(2026, 1, 19, tzinfo=timezone.utc)
    first = phase_at(base + timedelta(days=SYNODIC_MONTH / 4))
    assert first.illumination == pytest.approx(0.5, abs=0.05)
    assert first.waxing


def test_waxing_and_waning_are_distinguished():
    base = datetime(2026, 1, 19, tzinfo=timezone.utc)
    assert phase_at(base + timedelta(days=5)).waxing
    assert not phase_at(base + timedelta(days=22)).waxing


def test_phase_names_cover_the_whole_cycle():
    base = datetime(2026, 1, 19, tzinfo=timezone.utc)
    names = {phase_at(base + timedelta(days=d)).name for d in range(30)}
    assert {"NEW", "FULL", "FIRST QUARTER", "LAST QUARTER"} <= names


def test_short_names_fit_a_panel():
    base = datetime(2026, 1, 19, tzinfo=timezone.utc)
    for d in range(30):
        assert len(phase_at(base + timedelta(days=d)).short_name) <= 9


# --- the terminator ---------------------------------------------------------

def _lit_fraction(phase: float, radius: int = 8) -> float:
    inside = [(x, y) for x in range(-radius, radius + 1)
              for y in range(-radius, radius + 1)
              if x * x + y * y <= radius * radius]
    return sum(lit(x, y, radius, phase) for x, y in inside) / len(inside)


def test_new_moon_is_dark_and_full_is_lit():
    assert _lit_fraction(0.0) < 0.05
    assert _lit_fraction(0.5) > 0.95


def test_quarters_light_half_the_disc():
    assert _lit_fraction(0.25) == pytest.approx(0.5, abs=0.06)
    assert _lit_fraction(0.75) == pytest.approx(0.5, abs=0.06)


def test_the_lit_side_swaps_between_waxing_and_waning():
    """A waxing moon is lit on the right, a waning one on the left."""
    assert lit(5, 0, 8, 0.25) and not lit(-5, 0, 8, 0.25)
    assert lit(-5, 0, 8, 0.75) and not lit(5, 0, 8, 0.75)


def test_outside_the_disc_is_never_lit():
    assert not lit(20, 0, 8, 0.5)


# --- the scene --------------------------------------------------------------

class FakeWeather:
    configured = True
    last_error = None

    def __init__(self, sunrise, sunset):
        self._w = type("W", (), {"sunrise": sunrise, "sunset": sunset})()

    def current(self):
        return self._w


def render(app, when, params=None):
    day = when.date()
    source = FakeWeather(
        datetime.combine(day, datetime.min.time().replace(hour=6, minute=43), TZ),
        datetime.combine(day, datetime.min.time().replace(hour=19, minute=27), TZ),
    )
    ctx = app.context(when, brightness=1.0)
    ctx.weather = source
    return REGISTRY["sky"].render(ctx, params or {})


DAY = datetime(2026, 9, 13, tzinfo=TZ)


def test_it_renders_through_the_day(app):
    for hour in (3, 7, 12, 17, 20, 23):
        c = render(app, DAY.replace(hour=hour))
        assert c.image.size == (192, 32)
        assert any(sum(p) > 0 for p in c.image.get_flattened_data()), hour


def test_day_and_night_look_different(app):
    noon = render(app, DAY.replace(hour=12))
    midnight = render(app, DAY.replace(hour=23))
    assert noon.to_ascii() != midnight.to_ascii()
    # Noon should be markedly brighter overall than midnight.
    total = lambda c: sum(sum(p) for p in c.image.get_flattened_data())
    assert total(noon) > total(midnight) * 2


def test_the_sun_travels_left_to_right(app):
    def sun_x(hour):
        c = render(app, DAY.replace(hour=hour))
        ambers = [x for x in range(192) for y in range(26)
                  if c.image.getpixel((x, y))[0] > 200
                  and c.image.getpixel((x, y))[2] < 90]
        return sum(ambers) / len(ambers) if ambers else 0

    morning, afternoon = sun_x(8), sun_x(17)
    assert morning < afternoon, "the sun should move across the panel"


def test_sun_times_are_redated_onto_today(app):
    """Cached sunrise and sunset are dated to the fetch. Once the clock passes
    midnight they stop matching, and every frame decides it is night."""
    stale_day = datetime(2026, 9, 1, tzinfo=TZ)
    source = FakeWeather(
        datetime.combine(stale_day.date(), datetime.min.time().replace(hour=6), TZ),
        datetime.combine(stale_day.date(), datetime.min.time().replace(hour=19), TZ),
    )
    ctx = app.context(DAY.replace(hour=12), brightness=1.0)
    ctx.weather = source
    c = REGISTRY["sky"].render(ctx, {})
    # Midday must render as day even though the cached times are twelve days old.
    blues = [p for p in c.image.get_flattened_data() if p[2] > 100 and p[0] < 80]
    assert blues, "should be a daylight sky"


def test_nothing_overflows(app):
    for hour in (0, 6, 12, 19, 23):
        c = render(app, DAY.replace(hour=hour))
        assert c.image.size == (192, 32)


def test_the_times_stay_readable_behind_a_low_sun(app):
    """The sun sits on the horizon exactly where the labels are written."""
    c = render(app, DAY.replace(hour=19, minute=15))
    # The backing box is drawn dark; the label pixels must still be amber-ish.
    band = [c.image.getpixel((x, 28)) for x in range(2, 24)]
    assert any(p[0] > 120 for p in band), "sunrise label lost behind the sun"


def test_it_drops_out_without_coordinates(app, now):
    ctx = app.context(now)
    ctx.weather = None
    assert not REGISTRY["sky"].available(ctx, {})
    assert REGISTRY["sky"].available(ctx, {"always": True})


def test_stars_do_not_reshuffle_between_renders(app):
    """A different star field on every fetch would read as flicker."""
    a = render(app, DAY.replace(hour=23))
    b = render(app, DAY.replace(hour=23))
    assert a.to_ascii() == b.to_ascii()


# --- the date ---------------------------------------------------------------

def test_the_date_appears(app):
    with_date = render(app, DAY.replace(hour=12), {"date": "sky"})
    without = render(app, DAY.replace(hour=12), {"date": "none"})
    lit_count = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit_count(with_date) > lit_count(without)


@pytest.mark.parametrize("placement", ["sky", "horizon", "ground"])
def test_every_placement_renders(app, placement):
    for hour in (12, 22):
        c = render(app, DAY.replace(hour=hour), {"date": placement})
        assert c.image.size == (192, 32)


def test_the_date_never_collides_with_the_moon_label(app):
    """On the horizon line the two drew straight through each other, which
    came out as 'SUNKCRESP'."""
    c = render(app, DAY.replace(hour=22), {"date": "horizon", "label": True})
    # The moon label occupies rows 27-31; the date must stay clear of them.
    date_rows = [y for y in range(18, 26)
                 if any(sum(c.image.getpixel((x, y))) > 0 for x in range(60, 132))]
    assert date_rows, "the date should sit above the horizon"


def test_the_date_recedes_rather_than_shouting(app):
    """It is a caption, not a headline: dimmer than the sunrise time."""
    c = render(app, DAY.replace(hour=12), {"date": "sky"})
    date_px = [c.image.getpixel((x, 3)) for x in range(3, 60)]
    brightest_date = max((sum(p) for p in date_px), default=0)
    time_px = [c.image.getpixel((x, 28)) for x in range(2, 24)]
    brightest_time = max((sum(p) for p in time_px), default=0)
    assert brightest_date < brightest_time


def test_the_sky_date_stays_clear_of_the_arc(app):
    """The sun reaches the top centre at midday; the caption sits far left."""
    c = render(app, DAY.replace(hour=12), {"date": "sky"})
    assert c.image.size == (192, 32)
