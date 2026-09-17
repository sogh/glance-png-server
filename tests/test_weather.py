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


def test_labels_fit_the_detail_column():
    """The old guard counted characters. The panel bills in pixels.

    "PARTLY SUNNY" is twelve characters, passed, and then rendered as
    "PARTLY SUN..." on stock settings -- 45px of label in a 43px column.

    The geometry below is the scene's, restated: change the layout and this
    has to move with it, which is the point. The budget is a real number, not
    a round one somebody guessed.
    """
    from glance.fonts import get_font
    from glance.scenes.weather import FORECAST_COLUMN

    small, big = get_font("3x5"), get_font("5x7")
    right, left = 192 - 8, 8                      # 192px panel, 8px margins
    temp_x = left + 22 + 5                        # icon, then a gap
    detail_x = temp_x + big.measure("66\u00b0") * 2 + 7   # hero temp at scale 2
    room = right - detail_x - (3 * FORECAST_COLUMN + 4)   # three forecast columns

    for condition in sorted(set(WMO.values())):
        label = Weather(60, 60, 70, 50, condition, True).label
        assert small.measure(label) <= room, \
            f"{label!r} is {small.measure(label)}px in a {room}px column"


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


# --- the bugs the sweep across every condition turned up --------------------

@pytest.mark.parametrize("size,y", [(12, 8), (22, 5)])
def test_every_icon_stays_inside_its_box(size, y):
    """The box is the forecast column's layout: weekday directly above, high
    directly below. An icon that spills lands in the text.

    `fog` dropped its bottom bar five rows past the box and struck through the
    high; `partly` lifted its sun clear of the top and put three rows of rays
    into the weekday, turning SUN into SUD. `thunder` and `clear` were a pixel
    or two out in ways that happened not to collide yet.
    """
    from glance import weathericons as wi
    from glance.canvas import Canvas

    pad = 30
    for condition in sorted(wi.ICONS):
        for night in (False, True):
            c = Canvas(size + 2 * pad)
            c.clear("black")
            wi.draw(c, condition, pad, y, size, night=night)
            ink = [(x - pad, row) for x in range(c.width) for row in range(32)
                   if c.image.getpixel((x, row)) != (0, 0, 0)]
            when = f"{condition} at {size}px, {'night' if night else 'day'}"
            assert ink, f"{when} drew nothing at all"
            assert min(r for _, r in ink) >= y, f"{when} draws above its box"
            assert max(r for _, r in ink) <= y + size - 1, f"{when} draws below its box"
            assert min(col for col, _ in ink) >= 0, f"{when} draws left of its box"
            assert max(col for col, _ in ink) <= size - 1, f"{when} draws right of its box"


@pytest.mark.parametrize("condition", sorted(set(WMO.values())))
def test_every_condition_clears_both_edges(app, condition):
    """The margin test only ever ran `clear`, which was one of the two
    conditions that passed. The other six hung a cloud pixel inside it."""
    ctx = app.context(brightness=1.0)
    ctx.weather = FakeSource(Weather(64, 62, 65, 52, condition, True, forecast=_days()))
    c = REGISTRY["weather"].render(ctx, {"margin": 8})
    lit = [x for x in range(c.width) for y in range(32)
           if c.image.getpixel((x, y)) != (0, 0, 0)]
    assert min(lit) >= 8, f"{condition}: ink at x={min(lit)}, inside the margin"
    assert max(lit) <= c.width - 8, f"{condition}: ink at x={max(lit)}"


def _icon_pixels(c, left=8, width=22):
    return [c.image.getpixel((x, y)) for x in range(left, left + width) for y in range(32)]


def test_a_partly_cloudy_night_is_not_sunny(app):
    """`night` reached `clear` and nothing else, so 2am under a broken sky
    drew full sunshine."""
    day = render(app, Weather(60, 60, 70, 50, "partly", True))
    night = render(app, Weather(60, 60, 70, 50, "partly", False))
    assert day.to_ascii() != night.to_ascii()

    def amber(pixels):
        return [p for p in pixels if p[0] > 200 and p[1] > 120 and p[2] < 60]

    assert amber(_icon_pixels(day)), "the sun should be out by day"
    assert not amber(_icon_pixels(night)), "the sun is out at night"


def test_the_moon_is_cut_with_the_panel_background(app):
    """The crescent is a disc bitten by a second disc. That bite was a literal
    black, so on any other background it read as a hole rather than a moon."""
    c = render(app, Weather(48, 45, 55, 42, "clear", False), {"background": "indigo"})
    assert (0, 0, 0) not in _icon_pixels(c), "the crescent was cut with black"


def test_the_aqi_number_is_never_orphaned(app):
    """The word and the number are one reading. Split across the fit check, a
    tight line kept the grey "AQI" and dropped the number -- which is the part
    that carries both the value and the colour of its band."""
    tight = dict(precip_chance=100, forecast=_days())
    with_aqi = render(app, Weather(-15, -22, 100, -20, "snow", True, aqi=201, **tight),
                      {"feels": True})
    without = render(app, Weather(-15, -22, 100, -20, "snow", True, aqi=None, **tight),
                     {"feels": True})
    assert with_aqi.to_ascii() == without.to_ascii(), \
        "an AQI that does not fit must leave nothing behind"

    # And the case is only meaningful if a roomy panel still draws it.
    roomy = render(app, Weather(60, 60, 70, 50, "cloudy", True, aqi=201))
    assert roomy.to_ascii() != render(app, Weather(60, 60, 70, 50, "cloudy", True)).to_ascii()


def test_the_high_low_gives_up_words_rather_than_truncating():
    from glance.fonts import get_font
    from glance.scenes.weather import _high_low

    small = get_font("3x5")
    assert _high_low(70, 52, 60, small) == "H 70  L 52"       # room for the lot
    for room in range(4, 61):
        line = _high_low(100, -20, room, small)
        assert "\u2026" not in line, f"truncated at room={room}"
        assert small.measure(line) <= room, f"overran room={room}"
        if line:
            assert "100" in line, "the high is the last thing to go"
    assert _high_low(100, -20, 4, small) == "", "nothing fits, so draw nothing"


def test_a_trace_of_rain_does_not_report_none(app):
    """`.00IN` claims rain and reports none in the same breath."""
    trace = Weather(60, 60, 70, 50, "rain", True, precip_chance=20, precip_now=0.004)
    assert trace.precip_text == "20%"
    assert Weather(60, 60, 70, 50, "rain", True, precip_now=0.04).precip_text == ".04IN"


def test_an_empty_daily_block_keeps_the_current_temperature(tmp_path: Path):
    """The key can be present with an empty list behind it. Indexing that threw
    away a perfectly good current reading and blanked the whole panel."""
    src = WeatherSource(45.5, -122.7, tmp_path, refresh=99999)
    src.cache_file.write_text(json.dumps({
        "current": {"temperature_2m": 66.1, "weather_code": 3, "is_day": 1},
        "daily": {"temperature_2m_max": [], "temperature_2m_min": []},
    }))
    w = src.current()
    assert w is not None, "a bad daily block must not cost us the temperature"
    assert w.temperature == 66
    assert w.high == 66 and w.low == 66


def test_air_quality_is_not_refetched_on_the_forecast_clock(primed, monkeypatch):
    """Caching it separately was the whole point; giving it the forecast's own
    15-minute interval meant four calls per hourly reading."""
    import os
    import time as time_mod

    from glance.sources import weather as weather_mod

    assert primed.air_refresh == 3600
    primed.air_cache_file.write_text(json.dumps({"current": {"us_aqi": 42}}))
    stamp = time_mod.time() - 1200        # 20 min: past `refresh`, inside the hour
    os.utime(primed.air_cache_file, (stamp, stamp))

    def boom(*args, **kwargs):
        raise AssertionError("refetched hourly data on the 15-minute clock")

    monkeypatch.setattr(weather_mod.httpx, "get", boom)
    assert (primed._air() or {}).get("current", {}).get("us_aqi") == 42


def test_the_weather_is_built_once_per_frame(primed, monkeypatch):
    """`current()` is called to decide the scene is in the rotation and again
    to draw it, and each call re-read and re-parsed two cache files."""
    calls = []
    original = primed._payload
    monkeypatch.setattr(primed, "_payload", lambda: calls.append(1) or original())
    assert primed.current() is not None
    assert primed.current() is not None
    assert len(calls) == 1
