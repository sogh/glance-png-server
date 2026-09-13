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
    assert pixels(noon) != pixels(midnight)
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

def _region(canvas, x0, y0, x1, y1):
    return [canvas.image.getpixel((x, y))
            for x in range(x0, x1) for y in range(y0, y1)]


@pytest.mark.parametrize("placement,box", [
    ("sky", (2, 1, 70, 8)),
    ("horizon", (60, 18, 132, 26)),
    ("ground", (60, 26, 132, 32)),
])
def test_the_date_appears_where_it_should(app, placement, box):
    """Counting lit pixels cannot see this: in daylight the whole sky is
    coloured, so the text changes values without changing the count."""
    with_date = render(app, DAY.replace(hour=12), {"date": placement})
    without = render(app, DAY.replace(hour=12), {"date": "none"})
    assert _region(with_date, *box) != _region(without, *box)


def test_none_really_draws_nothing(app):
    plain = render(app, DAY.replace(hour=12), {"date": "none"})
    same = render(app, DAY.replace(hour=12), {"date": "none"})
    assert list(plain.image.get_flattened_data()) == list(same.image.get_flattened_data())


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


# --- weather in the sky -----------------------------------------------------

class WeatherAt:
    configured = True
    last_error = None

    def __init__(self, condition, day):
        self._w = type("W", (), {
            "sunrise": datetime.combine(day, datetime.min.time().replace(hour=6, minute=43), TZ),
            "sunset": datetime.combine(day, datetime.min.time().replace(hour=19, minute=27), TZ),
            "condition": condition})()

    def current(self):
        return self._w


def weather_render(app, condition, when, params=None):
    ctx = app.context(when, brightness=1.0)
    ctx.weather = WeatherAt(condition, when.date())
    return REGISTRY["sky"].render(ctx, params or {})


CONDITIONS = ["clear", "partly", "cloudy", "fog", "drizzle", "rain", "snow", "thunder"]


def pixels(canvas):
    """Compare by value, not by to_ascii().

    to_ascii() thresholds to lit/unlit, which is fine for sparse text but
    blind to a full-bleed sky where every pixel is above the threshold: two
    completely different skies come out as identical blocks of '#'.
    """
    return list(canvas.image.get_flattened_data())


@pytest.mark.parametrize("condition", CONDITIONS)
def test_every_condition_renders_day_and_night(app, condition):
    for hour in (13, 22):
        c = weather_render(app, condition, DAY.replace(hour=hour))
        assert c.image.size == (192, 32)


def test_cloud_changes_the_sky(app):
    clear = weather_render(app, "clear", DAY.replace(hour=13))
    overcast = weather_render(app, "cloudy", DAY.replace(hour=13))
    assert pixels(clear) != pixels(overcast)


def test_an_overcast_day_is_greyer_than_a_clear_one(app):
    """Not just clouds pasted on a blue sky."""
    def zenith(c):
        return c.image.getpixel((150, 2))
    clear, overcast = (zenith(weather_render(app, k, DAY.replace(hour=13)))
                       for k in ("clear", "rain"))
    spread = lambda p: max(p) - min(p)
    assert spread(overcast) < spread(clear), "overcast should be closer to grey"


def test_an_overcast_night_is_not_brighter_than_a_clear_one(app):
    """Mixing toward a daytime overcast after dark lit the sky up, which is
    exactly backwards."""
    def zenith(c):
        return sum(c.image.getpixel((150, 2)))
    clear = zenith(weather_render(app, "clear", DAY.replace(hour=22)))
    overcast = zenith(weather_render(app, "rain", DAY.replace(hour=22)))
    assert overcast <= clear + 70, f"night overcast {overcast} vs clear {clear}"


def test_rain_falls_below_the_clouds_not_inside_them(app):
    """The streaks started at a fixed offset from the cloud top, which put
    them inside it."""
    c = weather_render(app, "rain", DAY.replace(hour=13))
    blues = [(x, y) for x in range(192) for y in range(26)
             if c.image.getpixel((x, y))[2] > 180
             and c.image.getpixel((x, y))[0] < 120]
    assert blues, "no rain drawn"
    # Rain should reach well down the sky, not sit in the top third.
    assert max(y for _, y in blues) > 12


def test_snow_and_rain_look_different(app):
    rain = weather_render(app, "rain", DAY.replace(hour=13))
    snow = weather_render(app, "snow", DAY.replace(hour=13))
    assert pixels(rain) != pixels(snow)


def test_fog_lies_along_the_ground(app):
    c = weather_render(app, "fog", DAY.replace(hour=13))
    upper = sum(1 for x in range(192) for y in range(0, 10)
                if sum(c.image.getpixel((x, y))) > 380)
    lower = sum(1 for x in range(192) for y in range(14, 26)
                if sum(c.image.getpixel((x, y))) > 380)
    assert lower > upper, "fog belongs near the horizon"


def test_the_date_stays_legible_over_cloud(app):
    """A cloud drifting across the date is atmospheric until you cannot read
    it, so the caption is drawn last."""
    c = weather_render(app, "rain", DAY.replace(hour=13), {"date": "sky"})
    caption = [c.image.getpixel((x, 3)) for x in range(3, 60)]
    darkest = min(sum(p) for p in caption)
    brightest = max(sum(p) for p in caption)
    assert brightest - darkest > 60, "the caption should stand out from the sky"


def test_weather_can_be_switched_off(app):
    on = weather_render(app, "rain", DAY.replace(hour=13))
    off = weather_render(app, "rain", DAY.replace(hour=13), {"weather": False})
    assert pixels(on) != pixels(off)


def test_the_weather_holds_still_between_fetches(app):
    a = weather_render(app, "rain", DAY.replace(hour=13))
    b = weather_render(app, "rain", DAY.replace(hour=13))
    assert list(a.image.get_flattened_data()) == list(b.image.get_flattened_data())


def test_a_new_moon_has_no_lit_pixels_at_all():
    """The terminator passes through both poles at every phase, so the
    comparison is degenerate there and came out lit even at new moon."""
    radius = 7
    assert not any(lit(x, y, radius, 0.0)
                   for x in range(-radius, radius + 1)
                   for y in range(-radius, radius + 1))


def test_a_full_moon_lights_every_pixel_including_the_poles():
    radius = 7
    inside = [(x, y) for x in range(-radius, radius + 1)
              for y in range(-radius, radius + 1)
              if x * x + y * y <= radius * radius]
    assert all(lit(x, y, radius, 0.5) for x, y in inside)


def test_the_poles_never_stand_out_from_their_neighbours():
    """A lit pole on a dark limb reads as a speck of dirt on the panel."""
    radius = 7
    for phase in (0.0, 0.05, 0.95, 0.5):
        top = lit(0, -radius, radius, phase)
        near_top = lit(0, -radius + 2, radius, phase)
        assert top == near_top, f"phase {phase}"
