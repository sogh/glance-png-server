"""Weather from Open-Meteo.

No test here touches the network: the source caches to disk, so priming the
cache file is enough to exercise everything downstream of the fetch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from glance.scenes import REGISTRY
from glance.sources.weather import WMO, Weather, WeatherSource

PAYLOAD = {
    "current": {"temperature_2m": 66.1, "apparent_temperature": 61.4,
                "weather_code": 3, "is_day": 1},
    "daily": {"temperature_2m_max": [67.0], "temperature_2m_min": [52.4],
              "weather_code": [3]},
}


@pytest.fixture
def primed(tmp_path: Path) -> WeatherSource:
    src = WeatherSource(45.5, -122.7, tmp_path, refresh=99999)
    src.cache_file.write_text(json.dumps(PAYLOAD))
    return src


def test_codes_cover_the_documented_range():
    for code in (0, 1, 2, 3, 45, 51, 61, 71, 80, 85, 95, 99):
        assert code in WMO, code
    assert WMO[0] == "clear" and WMO[95] == "thunder"


def test_reading_the_cache(primed):
    w = primed.current()
    assert (w.temperature, w.high, w.low) == (66, 67, 52)
    assert w.condition == "cloudy"
    assert w.is_day and w.unit == "F"
    assert primed.last_error is None


def test_values_are_rounded_for_display(primed):
    """A panel has no room for a decimal point."""
    w = primed.current()
    assert w.temperature == int(w.temperature)


def test_an_unconfigured_source_is_quiet(tmp_path: Path):
    src = WeatherSource(None, None, tmp_path)
    assert not src.configured
    assert src.current() is None


def test_a_failed_fetch_falls_back_to_the_cache(primed):
    primed.refresh = 0                       # force a fetch
    primed.latitude, primed.longitude = 45.5, -122.7
    object.__setattr__(primed, "timeout", 0.001)   # guarantee failure
    w = primed.current()
    assert w is not None, "stale weather beats a blank panel"


def test_a_malformed_payload_is_reported_not_raised(tmp_path: Path):
    src = WeatherSource(45.5, -122.7, tmp_path, refresh=99999)
    src.cache_file.write_text(json.dumps({"current": {"nonsense": 1}}))
    assert src.current() is None
    assert src.last_error


def test_labels_are_panel_sized():
    for condition in set(WMO.values()):
        w = Weather(60, 60, 70, 50, condition, True)
        assert len(w.label) <= 13, f"{condition} label too long for the strip"


# --- the scene --------------------------------------------------------------

class FakeSource:
    configured = True
    last_error = None

    def __init__(self, weather):
        self._w = weather

    def current(self):
        return self._w


def render(app, weather, params=None):
    ctx = app.context(brightness=1.0)
    ctx.weather = FakeSource(weather)
    return REGISTRY["weather"].render(ctx, params or {})


def test_the_scene_renders(app):
    c = render(app, Weather(66, 64, 70, 52, "cloudy", True))
    assert c.image.size == (192, 32)
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_hot_reads_warm_and_cold_reads_cool(app):
    hot = render(app, Weather(95, 99, 96, 70, "clear", True))
    cold = render(app, Weather(28, 20, 33, 24, "snow", True))
    oranges = [p for p in hot.image.get_flattened_data() if p[0] > 180 and p[2] < 80]
    blues = [p for p in cold.image.get_flattened_data() if p[2] > 150 and p[0] < 110]
    assert oranges and blues


def test_every_condition_draws_without_error(app):
    for condition in set(WMO.values()):
        c = render(app, Weather(60, 60, 70, 50, condition, True))
        assert any(sum(p) > 0 for p in c.image.get_flattened_data()), condition


def test_night_differs_from_day(app):
    day = render(app, Weather(60, 60, 70, 50, "clear", True))
    night = render(app, Weather(60, 60, 70, 50, "clear", False))
    assert day.to_ascii() != night.to_ascii()


def test_feels_like_is_hidden_when_it_matches(app):
    """`feels` is off by default now that precip and AQI earn that slot."""
    same = render(app, Weather(60, 60, 70, 50, "cloudy", True), {"feels": True})
    different = render(app, Weather(60, 48, 70, 50, "cloudy", True), {"feels": True})
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit(different) > lit(same)


def test_nothing_runs_off_the_edge(app):
    c = render(app, Weather(-15, -22, 100, -20, "snow", True))
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_it_drops_out_of_rotation_when_unconfigured(app, now):
    ctx = app.context(now)
    assert not REGISTRY["weather"].available(ctx, {})
    assert REGISTRY["weather"].available(ctx, {"always": True})


def test_unconfigured_says_what_to_do(app, now):
    c, label = app.render_scene("weather", {"always": True}, app.context(now))
    assert not label.startswith("error:")
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_it_fits_a_single_module(app):
    ctx = app.context(width=64, brightness=1.0)
    ctx.weather = FakeSource(Weather(66, 64, 70, 52, "rain", True))
    c = REGISTRY["weather"].render(ctx, {})
    assert c.width == 64
    edge = [c.image.getpixel((63, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


# --- precipitation and air quality -----------------------------------------

def test_aqi_bands_match_the_us_scale():
    from glance.sources.weather import aqi_band
    assert aqi_band(20)[0] == "GOOD"
    assert aqi_band(50)[0] == "GOOD"          # boundary belongs to the lower band
    assert aqi_band(51)[0] == "MODERATE"
    assert aqi_band(120)[0] == "SENSITIVE"
    assert aqi_band(180)[0] == "UNHEALTHY"
    assert aqi_band(250)[0] == "VERY BAD"
    assert aqi_band(500)[0] == "HAZARDOUS"
    assert aqi_band(None)[0] == ""


def test_aqi_colours_run_from_green_to_red():
    from glance.sources.weather import aqi_band
    assert aqi_band(20)[1] == "green"
    assert aqi_band(180)[1] == "red"


def test_falling_rain_beats_a_forecast_probability():
    """A 20% chance is not interesting while it is actually raining."""
    raining = Weather(60, 60, 70, 50, "rain", True, precip_chance=20, precip_now=0.04)
    dry = Weather(60, 60, 70, 50, "cloudy", True, precip_chance=20, precip_now=0.0)
    assert raining.precip_text.endswith("IN")
    assert dry.precip_text == "20%"


def test_no_precipitation_data_shows_nothing():
    assert Weather(60, 60, 70, 50, "clear", True).precip_text == ""


def test_the_scene_draws_precip_and_aqi(app):
    plain = render(app, Weather(60, 60, 70, 50, "cloudy", True))
    rich = render(app, Weather(60, 60, 70, 50, "cloudy", True,
                               precip_chance=40, aqi=68))
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit(rich) > lit(plain)


def test_a_bad_aqi_reads_red(app):
    c = render(app, Weather(60, 60, 70, 50, "cloudy", True, aqi=180))
    reds = [p for p in c.image.get_flattened_data() if p[0] > 180 and p[1] < 90 and p[2] < 90]
    assert reds, "an unhealthy AQI should be unmistakable"


def test_a_good_aqi_reads_green(app):
    c = render(app, Weather(60, 60, 70, 50, "cloudy", True, aqi=20))
    greens = [p for p in c.image.get_flattened_data() if p[1] > 150 and p[0] < 100]
    assert greens


def test_both_can_be_switched_off(app):
    on = render(app, Weather(60, 60, 70, 50, "cloudy", True, precip_chance=40, aqi=68))
    off = render(app, Weather(60, 60, 70, 50, "cloudy", True, precip_chance=40, aqi=68),
                 {"precip": False, "aqi": False})
    assert on.to_ascii() != off.to_ascii()


def test_the_extra_line_never_overflows(app):
    """Worst case: three-digit AQI, an amount falling, and feels-like."""
    c = render(app, Weather(-12, -20, 104, -18, "snow", True,
                            precip_chance=100, precip_now=1.25, aqi=487),
               {"feels": True})
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_air_quality_failing_does_not_lose_the_forecast(primed, tmp_path):
    """A second endpoint is a second thing that can break; it must not take
    the temperature down with it."""
    primed.air_quality = True
    object.__setattr__(primed, "timeout", 0.001)
    w = primed.current()
    assert w is not None and w.temperature == 66
    assert w.aqi is None


def test_air_quality_can_be_disabled(primed):
    primed.air_quality = False
    assert primed._air() is None


# --- multi-day forecast -----------------------------------------------------

def _days():
    from glance.sources.weather import DayForecast
    return [DayForecast("2026-09-13", "rain", 65, 54),
            DayForecast("2026-09-14", "clear", 78, 52),
            DayForecast("2026-09-15", "snow", 34, 28)]


def test_the_source_parses_following_days(primed, tmp_path):
    import json
    payload = json.loads(primed.cache_file.read_text())
    payload["daily"] = {
        "time": ["2026-09-12", "2026-09-13", "2026-09-14"],
        "temperature_2m_max": [67.0, 65.4, 78.2],
        "temperature_2m_min": [52.4, 54.1, 52.0],
        "weather_code": [3, 61, 0],
    }
    primed.cache_file.write_text(json.dumps(payload))
    w = primed.current()
    assert [d.date for d in w.forecast] == ["2026-09-13", "2026-09-14"], "today is excluded"
    assert w.forecast[0].condition == "rain"
    assert w.forecast[1].condition == "clear"
    assert w.forecast[1].high == 78


def test_the_forecast_is_drawn(app):
    without = render(app, Weather(60, 60, 70, 50, "cloudy", True))
    with_days = render(app, Weather(60, 60, 70, 50, "cloudy", True, forecast=_days()))
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit(with_days) > lit(without)


def test_the_forecast_can_be_turned_off(app):
    on = render(app, Weather(60, 60, 70, 50, "cloudy", True, forecast=_days()))
    off = render(app, Weather(60, 60, 70, 50, "cloudy", True, forecast=_days()),
                 {"forecast": 0})
    assert on.to_ascii() != off.to_ascii()


def test_fewer_days_leaves_more_room(app):
    three = render(app, Weather(60, 60, 70, 50, "cloudy", True, forecast=_days()))
    two = render(app, Weather(60, 60, 70, 50, "cloudy", True, forecast=_days()),
                 {"forecast": 2})
    assert three.to_ascii() != two.to_ascii()


def test_forecast_highs_are_colour_coded_too(app):
    c = render(app, Weather(60, 60, 70, 50, "cloudy", True, forecast=_days()))
    px = c.image.get_flattened_data()
    assert [p for p in px if p[0] > 180 and p[2] < 80], "78 should read warm"
    assert [p for p in px if p[2] > 150 and p[0] < 110], "34 should read cold"


def test_the_forecast_never_overflows_the_panel(app):
    c = render(app, Weather(-12, -20, 104, -18, "snow", True,
                            precip_chance=100, precip_now=1.25, aqi=487,
                            forecast=_days()), {"feels": True})
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_the_detail_text_yields_space_to_the_forecast(app):
    """Both compete for the same strip; the text must give way rather than
    draw over the columns."""
    wide = render(app, Weather(60, 60, 70, 50, "cloudy", True,
                               precip_chance=40, aqi=68))
    narrow = render(app, Weather(60, 60, 70, 50, "cloudy", True,
                                 precip_chance=40, aqi=68, forecast=_days()))
    assert wide.to_ascii() != narrow.to_ascii()


def test_a_small_sun_keeps_its_rays():
    """At the forecast icon size the ray loop computed an empty range, so
    'clear' drew as a bare disc indistinguishable from a full moon."""
    from glance.canvas import Canvas
    from glance import weathericons as wi
    c = Canvas(20)
    c.clear("black")
    wi.draw(c, "clear", 1, 1, 12)
    # Corners of the box can only be lit by rays, never by the disc.
    corners = [c.image.getpixel((x, y)) for x in (2, 14) for y in (2, 14)]
    assert any(sum(p) > 0 for p in corners), "no rays at 12px"


def test_the_pane_clears_both_edges(app):
    """The device pans one app straight into the next, so a pane inked end to
    end has nothing to say where it stops and its neighbour starts."""
    margin = 8
    ctx = app.context(brightness=1.0)
    ctx.weather = FakeSource(Weather(64, 62, 65, 52, "clear", True))
    c = REGISTRY["weather"].render(ctx, {"margin": margin})
    lit = [x for x in range(c.width) for y in range(32)
           if c.image.getpixel((x, y)) != (0, 0, 0)]
    assert min(lit) >= margin
    assert max(lit) <= c.width - margin


@pytest.mark.parametrize("width", [64, 96, 128, 192])
def test_a_forecast_column_that_will_not_fit_is_dropped(app, width):
    """Three columns is 63px. On a single 64px module the block was being
    placed at a negative x and bleeding back across the icon."""
    ctx = app.context(width=width, brightness=1.0)
    ctx.weather = FakeSource(Weather(64, 62, 65, 52, "clear", True))
    c = REGISTRY["weather"].render(ctx, {"margin": 8})
    lit = [x for x in range(c.width) for y in range(32)
           if c.image.getpixel((x, y)) != (0, 0, 0)]
    assert min(lit) >= 8, f"width {width}: ink at x={min(lit)}"
    assert max(lit) <= c.width - 8
