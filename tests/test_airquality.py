"""Air quality: measured where possible, modelled where not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from glance.sources.airquality import AirNowSource, Reading

HERE = (48.109, -122.442)          # Camano Island, WA
TULALIP = (48.0669, -122.2809)     # ~12.8 km
EVERETT = (47.9, -122.25)          # ~27 km
ANACORTES = (48.48, -122.6)        # ~43 km -- comfortably outside


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import glance.sources.airquality as mod

    def refuse(*a, **k):
        raise AssertionError("this test tried to use the network")

    monkeypatch.setattr(mod.httpx, "get", refuse)


def row(parameter, aqi, where, site, primary=False):
    return {"parameter": parameter, "aqi": aqi, "siteName": site,
            "latitude": where[0], "longitude": where[1], "isPrimary": primary,
            "validDate": "09/16/26", "time": "08:00", "timezone": "PDT",
            "category": "Good"}


def source(tmp_path, rows, **kw):
    src = AirNowSource(*HERE, cache_dir=tmp_path, **kw)
    src.cache_file.write_text(json.dumps(rows))
    return src


REAL = [row("PM2.5", 42, TULALIP, "Tulalip-36th Ave NW"),
        row("PM10", 69, EVERETT, "Everett-Beverly Park Rd", primary=True),
        row("OZONE", 4, ANACORTES, "Anacortes-202 Ave")]


# --- distance ---------------------------------------------------------------

def test_distance_is_measured_from_here(tmp_path):
    readings = source(tmp_path, REAL).readings()
    by_site = {r.station.split("-")[0]: r.distance_km for r in readings}
    assert by_site["Tulalip"] == pytest.approx(12.8, abs=1.0)
    assert by_site["Everett"] == pytest.approx(27.0, abs=2.0)
    assert by_site["Anacortes"] == pytest.approx(42.9, abs=1.0)


def test_readings_come_back_nearest_first(tmp_path):
    assert [r.pollutant for r in source(tmp_path, REAL).readings()] == [
        "PM2.5", "PM10", "OZONE"]


def test_a_distant_monitor_does_not_describe_your_garden(tmp_path):
    """The keyless endpoint returns the closest reading for each pollutant
    *separately*, so the plain EPA maximum here is PM10 from 27km away. That
    is somebody else's air."""
    src = source(tmp_path, REAL, max_distance=25)
    reading = src.current()
    assert reading.aqi == 42
    assert reading.pollutant == "PM2.5"
    assert reading.station.startswith("Tulalip")


def test_widening_the_radius_brings_the_worse_one_back(tmp_path):
    """Distance first, then the EPA rule -- not instead of it."""
    assert source(tmp_path, REAL, max_distance=30).current().aqi == 69


def test_the_worst_pollutant_wins_among_those_near_enough(tmp_path):
    rows = [row("PM2.5", 20, TULALIP, "A"), row("OZONE", 61, TULALIP, "A")]
    assert source(tmp_path, rows).current().aqi == 61


def test_nothing_near_enough_is_no_reading_at_all(tmp_path):
    """Better to say nothing and let the model answer than to report another
    county's air as this one's."""
    assert source(tmp_path, [row("PM2.5", 42, ANACORTES, "Far")],
                  max_distance=25).current() is None


# --- robustness -------------------------------------------------------------

def test_the_no_reading_sentinel_is_not_an_aqi_of_minus_one(tmp_path):
    rows = [row("PM2.5", -1, TULALIP, "A"), row("PM10", 30, TULALIP, "A")]
    assert source(tmp_path, rows).current().aqi == 30


def test_every_pollutant_missing_means_no_reading(tmp_path):
    assert source(tmp_path, [row("PM2.5", -1, TULALIP, "A")]).current() is None


def test_a_row_without_coordinates_is_kept_rather_than_dropped(tmp_path):
    """The official keyed API words things differently; a reading with no
    position is still a reading."""
    rows = [{"ParameterName": "PM2.5", "AQI": 33, "ReportingArea": "Marysville",
             "DateObserved": "2026-09-16", "HourObserved": 8}]
    reading = source(tmp_path, rows).current()
    assert reading.aqi == 33
    assert reading.station == "Marysville"
    assert reading.distance_km is None


def test_junk_rows_are_skipped_not_raised(tmp_path):
    rows = ["nonsense", 42, None, row("PM2.5", 30, TULALIP, "A")]
    assert source(tmp_path, rows).current().aqi == 30


def test_no_coordinates_is_reported_not_guessed(tmp_path):
    src = AirNowSource(None, None, cache_dir=tmp_path)
    assert not src.configured
    assert src.current() is None
    assert "no coordinates" in src.last_error


def test_a_reading_says_whether_an_instrument_made_it(tmp_path):
    assert source(tmp_path, REAL).current().measured
    assert not Reading(aqi=53, source="open-meteo").measured


# --- the fallback -----------------------------------------------------------

class Model:
    """Stands in for Open-Meteo's modelled figure."""

    configured, last_error, air_quality = True, None, True


def weather_with(tmp_path, air, monkeypatch):
    from glance.sources.weather import WeatherSource
    src = WeatherSource(*HERE, cache_dir=tmp_path, air_source=air)
    src.cache_file.write_text(json.dumps({
        "current": {"temperature_2m": 64, "apparent_temperature": 62,
                    "weather_code": 0, "is_day": 1, "precipitation": 0},
        "daily": {"temperature_2m_max": [70], "temperature_2m_min": [52],
                  "precipitation_probability_max": [8],
                  "sunrise": ["2026-09-16T06:44"], "sunset": ["2026-09-16T19:25"]},
    }))
    src.air_cache_file.write_text(json.dumps({"current": {"us_aqi": 53, "pm2_5": 15.1}}))
    return src


def test_a_measured_reading_wins_over_the_model(tmp_path, monkeypatch):
    src = weather_with(tmp_path, source(tmp_path, REAL), monkeypatch)
    reading = src.current()
    assert reading.aqi == 42
    assert reading.aqi_source == "airnow"
    assert reading.aqi_station.startswith("Tulalip")


def test_the_model_answers_when_no_monitor_is_close(tmp_path, monkeypatch):
    far = source(tmp_path, [row("PM2.5", 42, ANACORTES, "Far")], max_distance=25)
    reading = weather_with(tmp_path, far, monkeypatch).current()
    assert reading.aqi == 53
    assert reading.aqi_source == "open-meteo"


def test_a_broken_monitor_feed_falls_back_rather_than_failing(tmp_path, monkeypatch):
    class Broken:
        def current(self): raise RuntimeError("boom")

    reading = weather_with(tmp_path, Broken(), monkeypatch).current()
    assert reading.aqi == 53
    assert reading.aqi_source == "open-meteo"


def test_with_no_monitor_source_at_all_nothing_changes(tmp_path, monkeypatch):
    reading = weather_with(tmp_path, None, monkeypatch).current()
    assert reading.aqi == 53
    assert reading.aqi_source == "open-meteo"
