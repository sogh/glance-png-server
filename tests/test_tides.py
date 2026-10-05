"""Tides: the curve between the turns, the station, and the panel."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from glance.scenes.tides import curve, height_text, render_tides
from glance.sources.tides import TideSource, Tides, parse_predictions

TZ = ZoneInfo("America/Los_Angeles")
HERE = (48.109, -122.442)          # Camano Island, WA

# Kayak Point, 1-3 Oct 2026, as NOAA returned it in GMT. Puget Sound's tide is
# mixed: a big swing and a small one each day, which is the case that catches
# anything assuming two equal highs.
PREDICTIONS = [
    {"t": "2026-10-01 10:21", "v": "-1.666", "type": "L"},
    {"t": "2026-10-01 16:37", "v": "10.712", "type": "H"},
    {"t": "2026-10-01 21:55", "v": "7.264", "type": "L"},
    {"t": "2026-10-02 02:58", "v": "10.456", "type": "H"},
    {"t": "2026-10-02 10:19", "v": "-1.452", "type": "L"},
    {"t": "2026-10-02 17:53", "v": "10.465", "type": "H"},
    {"t": "2026-10-02 23:02", "v": "7.861", "type": "L"},
    {"t": "2026-10-03 03:48", "v": "9.842", "type": "H"},
    {"t": "2026-10-03 11:19", "v": "-0.981", "type": "L"},
    {"t": "2026-10-03 19:12", "v": "10.402", "type": "H"},
]


def local(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import glance.sources.tides as mod

    def refuse(*a, **k):
        raise AssertionError("this test tried to use the network")

    monkeypatch.setattr(mod.httpx, "get", refuse)


@pytest.fixture
def tides() -> Tides:
    events = parse_predictions(PREDICTIONS)
    for e in events:
        e.when = e.when.astimezone(TZ)
    return Tides(events=events, station="9448094", station_name="Kayak Point")


class Stub:
    last_error = None

    def __init__(self, value):
        self._value = value

    def current(self):
        return self._value


def panel(app, at, value, width=None, **params):
    ctx = app.context(at, width=width)
    ctx.tides = Stub(value)
    return render_tides(ctx, params)


# --- the curve between the turns -------------------------------------------

def test_the_turns_are_exact(tides):
    high = local(2, 10, 53)            # 17:53 GMT
    assert tides.height_at(high) == pytest.approx(10.465)


def test_halfway_between_turns_is_halfway_up(tides):
    low, high = local(2, 3, 19), local(2, 10, 53)
    mid = low + (high - low) / 2
    assert tides.height_at(mid) == pytest.approx((-1.452 + 10.465) / 2)


def test_the_water_moves_slowest_at_the_turn(tides):
    """Half a cosine, not a straight line: slack at the top, fast in the middle."""
    low, high = local(2, 3, 19), local(2, 10, 53)
    step = timedelta(minutes=30)
    mid = low + (high - low) / 2
    near_top = tides.height_at(high) - tides.height_at(high - step)
    in_middle = tides.height_at(mid + step / 2) - tides.height_at(mid - step / 2)
    assert in_middle > near_top * 4


def test_outside_the_predictions_is_unknown(tides):
    assert tides.height_at(local(1, 0)) is None
    assert tides.rising(local(5, 0)) is None


def test_heading_for_a_high_is_rising(tides):
    assert tides.rising(local(2, 6)) is True
    assert tides.rising(local(2, 13)) is False


def test_upcoming_is_in_order_and_strictly_after(tides):
    at = local(2, 10, 53)
    nxt = tides.upcoming(at, 2)
    assert [e.kind for e in nxt] == ["L", "H"]
    assert all(e.when > at for e in nxt)


def test_times_arrive_in_utc_and_rows_that_are_junk_are_dropped():
    events = parse_predictions(PREDICTIONS[:2] + [{"t": "never", "v": "1", "type": "H"},
                                                  {"t": "2026-10-01 12:00", "v": "x"}])
    assert len(events) == 2
    assert events[0].when.tzinfo is timezone.utc


@pytest.mark.parametrize("value, text", [
    (10.465, "10.5"), (-1.452, "-1.5"), (-0.04, "0.0"), (0.0, "0.0"), (7.861, "7.9"),
])
def test_height_text(value, text):
    assert height_text(value) == text


def test_the_graph_fills_its_box_and_marks_the_low_lowest(tides):
    ys = curve(tides, local(2, 14, 30), 52, 4, 27)
    assert None not in ys
    assert min(ys) == 4 and max(ys) == 27
    # Tomorrow's -1.0 low, about 14 hours on, is the deepest water in view.
    lowest = ys.index(max(ys))
    assert 52 * 17 / 24 < lowest < 52 * 21 / 24


# --- the source -------------------------------------------------------------

def seed(src: TideSource, **extra):
    payload = {"station": "9448094", "name": "Kayak Point", "km": 6.4,
               "units": src.units, "predictions": PREDICTIONS, **extra}
    src.cache_file.write_text(json.dumps(payload))


def test_a_fresh_cache_is_served_without_fetching(tmp_path):
    src = TideSource(tmp_path, latitude=HERE[0], longitude=HERE[1], tz=TZ)
    seed(src)
    tides = src.current()
    assert tides.station_name == "Kayak Point"
    assert tides.events[0].when.tzinfo == TZ
    assert tides.unit == "ft"


def test_a_stale_cache_beats_nothing_when_the_fetch_fails(tmp_path):
    src = TideSource(tmp_path, station="9448094", tz=TZ)
    seed(src)
    old = time.time() - 86400
    os.utime(src.cache_file, (old, old))
    assert src.current() is not None
    assert "AssertionError" in src.last_error


def test_a_cache_for_another_station_is_not_used(tmp_path):
    src = TideSource(tmp_path, station="9447130", tz=TZ)
    seed(src)
    assert src.current() is None


def test_a_cache_in_other_units_is_not_used(tmp_path):
    src = TideSource(tmp_path, station="9448094", units="metric", tz=TZ)
    seed(src, units="english")
    assert src.current() is None


def test_the_nearest_station_is_chosen(tmp_path):
    src = TideSource(tmp_path, latitude=HERE[0], longitude=HERE[1])
    src.stations_file.write_text(json.dumps([
        {"id": "9447130", "name": "Seattle", "lat": 47.6026, "lng": -122.3393},
        {"id": "9448094", "name": "Kayak Point", "lat": 48.1367, "lng": -122.3683},
        {"id": "9449880", "name": "Friday Harbor", "lat": 48.5453, "lng": -123.0125},
    ]))
    station, name, km = src.resolve_station()
    assert (station, name) == ("9448094", "Kayak Point")
    assert km == pytest.approx(6.4, abs=1.0)


def test_an_explicit_station_wins(tmp_path):
    src = TideSource(tmp_path, station="9447130", latitude=HERE[0], longitude=HERE[1])
    assert src.resolve_station()[0] == "9447130"


def test_no_station_and_no_coordinates_is_not_configured(tmp_path):
    src = TideSource(tmp_path)
    assert src.configured is False
    assert src.current() is None


# --- the panel --------------------------------------------------------------

@pytest.mark.parametrize("hour", [0, 3, 6, 10, 13, 16, 20, 23])
def test_it_renders_through_the_day(app, tides, hour):
    c = panel(app, local(2, hour), tides)
    assert c.image.size == (192, 32)
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_nothing_runs_off_the_edge(app, tides):
    for count in (1, 2, 4):
        c = panel(app, local(2, 22, 30), tides, count=count)
        for x in (0, c.width - 1):
            assert all(sum(c.image.getpixel((x, y))) == 0 for y in range(32))


def test_a_single_module_keeps_the_reading(app, tides):
    c = panel(app, local(2, 14), tides, width=64)
    assert c.width == 64
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())
    assert all(sum(c.image.getpixel((63, y))) == 0 for y in range(32))


def test_the_slack_tide_says_so(app, tides):
    """At the turn, RISING is true by a centimetre and wrong by the beach."""
    at_turn = panel(app, local(2, 10, 50), tides, graph=False, count=1)
    moving = panel(app, local(2, 8, 0), tides, graph=False, count=1)
    assert at_turn.to_ascii() != moving.to_ascii()


def test_turning_the_graph_off_draws_less(app, tides):
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    at = local(2, 14)
    assert lit(panel(app, at, tides)) > lit(panel(app, at, tides, graph=False))


def test_more_rows_draw_more(app, tides):
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    at = local(2, 14)
    assert lit(panel(app, at, tides, count=3)) > lit(panel(app, at, tides, count=1))


def test_no_tide_source_says_so(app):
    c = panel(app, local(2, 14), None)
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_out_of_range_says_so_rather_than_drawing_a_flat_sea(app, tides):
    c = panel(app, local(9, 14), tides)
    assert c.to_ascii() == panel(app, local(9, 14), None).to_ascii()


def test_availability_follows_the_data(app, tides):
    from glance.scenes.tides import _available
    ctx = app.context(local(2, 14))
    ctx.tides = Stub(tides)
    assert _available(ctx, {}) is True
    ctx.tides = Stub(None)
    assert _available(ctx, {}) is False
    ctx = app.context(local(9, 14))
    ctx.tides = Stub(tides)
    assert _available(ctx, {}) is False


# --- the day's range --------------------------------------------------------

def test_the_days_range_includes_turns_already_past(tides):
    """By afternoon the morning's minus tide is no longer next, but it was today's."""
    high, low = tides.day_range(local(2, 16).date())
    assert high.height == pytest.approx(10.465)       # 10:53am
    assert low.height == pytest.approx(-1.452)        # 3:19am, long gone by 4pm


def test_the_days_range_uses_local_days_not_utc(tides):
    # 23:02 GMT on the 2nd is 4:02pm local on the 2nd; 02:58 GMT on the 2nd
    # is 7:58pm local on the 1st and must not count towards the 2nd.
    high, low = tides.day_range(local(2, 12).date())
    assert all(e.when.date() == local(2, 12).date() for e in (high, low))
    assert high.when.hour == 10


def test_a_day_outside_the_predictions_has_no_range(tides):
    assert tides.day_range(local(9, 12).date()) is None


def test_the_days_range_adds_rows(app, tides):
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    at = local(2, 16)
    assert lit(panel(app, at, tides)) > lit(panel(app, at, tides, day=False))


def test_with_the_days_range_the_table_stays_at_four_rows(app, tides):
    """Six rows would not fit 32px at a readable size, so count gives way."""
    at = local(2, 16)
    assert (panel(app, at, tides, count=4).to_ascii()
            == panel(app, at, tides, count=2).to_ascii())
