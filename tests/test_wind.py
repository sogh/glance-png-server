"""The wind panel: bands, the intensity graphic, and what it hides."""

from __future__ import annotations

import pytest

from glance.scenes.wind import band_for, point_for, render_wind, streak_lengths
from glance.sources.weather import Weather


class Stub:
    last_error = None

    def __init__(self, weather):
        self._weather = weather

    def current(self):
        return self._weather


def blow(wind, gusts=None, direction=180):
    return Weather(temperature=59, feels_like=57, high=65, low=49,
                   condition="clear", is_day=True,
                   wind=wind, gusts=gusts, wind_dir=direction)


def panel(app, now, wind, gusts=None, direction=180, **params):
    ctx = app.context(now)
    ctx.weather = Stub(blow(wind, gusts, direction))
    return render_wind(ctx, params)


def test_the_speed_survives_on_a_single_module(app, now):
    """Whatever else is shed, the number is the reason the panel exists."""
    ctx = app.context(now, width=64)
    ctx.weather = Stub(blow(31, 44, 225))
    assert any(sum(p) > 0 for p in render_wind(ctx, {}).image.get_flattened_data())


# --- the scale --------------------------------------------------------------

@pytest.mark.parametrize("speed, name", [
    (0, "CALM"), (3, "CALM"), (4, "LIGHT"), (12, "LIGHT"),
    (13, "BREEZY"), (24, "BREEZY"), (25, "WINDY"), (38, "WINDY"),
    (39, "GALE"), (54, "GALE"), (55, "STORM"), (120, "STORM"),
])
def test_bands_cover_the_scale_without_a_gap(speed, name):
    assert band_for(speed)[1] == name


def test_the_level_rises_with_the_wind():
    levels = [band_for(s)[0] for s in (1, 8, 20, 30, 45, 70)]
    assert levels == sorted(levels) and levels[0] < levels[-1]


@pytest.mark.parametrize("degrees, point", [
    (0, "N"), (20, "N"), (45, "NE"), (90, "E"), (180, "S"),
    (225, "SW"), (270, "W"), (315, "NW"), (350, "N"), (359, "N"),
])
def test_the_compass_wraps(degrees, point):
    assert point_for(degrees) == point


def test_no_direction_means_no_point():
    assert point_for(None) == ""


# --- the graphic ------------------------------------------------------------

def test_the_streaks_grow_with_the_band():
    """The graphic is the point: it has to read without the number."""
    calm, storm = streak_lengths(46, 0), streak_lengths(46, 5)
    assert len(storm) > len(calm), "a storm should draw more lines"
    assert max(storm) > max(calm) * 2, "and much longer ones"


def test_the_streaks_are_staggered():
    """A stack of identical rules reads as a barcode, not as movement."""
    lengths = streak_lengths(46, 4)
    assert len(set(lengths)) > 1


def test_the_stack_never_outgrows_the_panel():
    for level in range(6):
        assert len(streak_lengths(46, level)) * 4 <= 32


# --- rendering --------------------------------------------------------------

@pytest.mark.parametrize("speed", [0, 2, 9, 18, 31, 47, 66, 130])
def test_it_renders_at_every_strength(app, now, speed):
    c = panel(app, now, speed, gusts=speed + 10)
    assert c.image.size == (192, 32)
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_nothing_runs_off_the_edge(app, now):
    c = panel(app, now, 131, gusts=180, direction=225)
    for x in (0, c.width - 1):
        assert all(sum(c.image.getpixel((x, y))) == 0 for y in range(32))


def test_a_narrow_panel_still_fits(app, now):
    ctx = app.context(now, width=64)
    ctx.weather = Stub(blow(31, 44, 225))
    c = render_wind(ctx, {})
    assert c.width == 64
    assert all(sum(c.image.getpixel((63, y))) == 0 for y in range(32))


# --- what it leaves out -----------------------------------------------------

def test_a_gust_barely_above_the_wind_is_not_worth_the_space(app, now):
    """A ratio alone reports G4 on a 2mph afternoon: true, and useless."""
    quiet = panel(app, now, 2, gusts=4).to_ascii()
    windy = panel(app, now, 31, gusts=44).to_ascii()
    assert quiet != windy
    bare = panel(app, now, 2, gusts=None).to_ascii()
    assert quiet == bare, "a 2mph gust of 4 should draw nothing extra"


def test_turning_the_extras_off_draws_less(app, now):
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    ctx = app.context(now)
    ctx.weather = Stub(blow(31, 44, 225))
    full = render_wind(ctx, {})
    bare = render_wind(ctx, {"band": False, "direction": False, "gusts": False})
    assert lit(full) > lit(bare)


def test_no_wind_data_says_so_rather_than_crashing(app, now):
    ctx = app.context(now)
    ctx.weather = Stub(blow(None))
    c = render_wind(ctx, {})
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_no_weather_source_at_all(app, now):
    ctx = app.context(now)
    ctx.weather = None
    c = render_wind(ctx, {})
    assert c.image.size == (192, 32)


# --- availability -----------------------------------------------------------

def test_a_floor_keeps_the_panel_out_of_the_rotation(app, now):
    from glance.scenes.wind import _available
    ctx = app.context(now)
    ctx.weather = Stub(blow(6))
    assert _available(ctx, {}) is True
    assert _available(ctx, {"floor": 15}) is False
    ctx.weather = Stub(blow(22))
    assert _available(ctx, {"floor": 15}) is True


def test_no_wind_reading_means_not_available(app, now):
    from glance.scenes.wind import _available
    ctx = app.context(now)
    ctx.weather = Stub(blow(None))
    assert _available(ctx, {}) is False
