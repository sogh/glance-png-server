"""Weather from Open-Meteo.

Chosen because it needs no API key and no account -- just coordinates. One
call returns current conditions and today's high and low, in under a kilobyte.

As with the calendar, a failed fetch serves the cached copy: a slightly stale
temperature beats a blank panel.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datetime import datetime

from zoneinfo import ZoneInfo

import httpx

ENDPOINT = "https://api.open-meteo.com/v1/forecast"
# Air quality lives on a different host and updates hourly rather than every
# 15 minutes, so it is fetched and cached separately.
AIR_ENDPOINT = "https://air-quality-api.open-meteo.com/v1/air-quality"

# US AQI bands. The colour carries the meaning here -- a number alone tells
# you nothing unless you already know the scale.
AQI_BANDS = [
    (50, "GOOD", "green"),
    (100, "MODERATE", "yellow"),
    (150, "SENSITIVE", "orange"),
    (200, "UNHEALTHY", "red"),
    (300, "VERY BAD", "purple"),
    (10_000, "HAZARDOUS", "crimson"),
]


def aqi_band(value: float | None) -> tuple[str, str]:
    """Label and colour for a US AQI reading."""
    if value is None:
        return "", "grey"
    for ceiling, label, color in AQI_BANDS:
        if value <= ceiling:
            return label, color
    return "HAZARDOUS", "crimson"

# WMO weather interpretation codes, collapsed to the handful of conditions
# worth drawing differently at 20 pixels across.
WMO = {
    0: "clear",
    1: "clear", 2: "partly", 3: "cloudy",
    45: "fog", 48: "fog",
    51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
    61: "rain", 63: "rain", 65: "rain", 66: "rain", 67: "rain",
    71: "snow", 73: "snow", 75: "snow", 77: "snow",
    80: "rain", 81: "rain", 82: "rain",
    85: "snow", 86: "snow",
    95: "thunder", 96: "thunder", 99: "thunder",
}

# Kept short enough to fit the detail column at its narrowest, which is what
# the panel actually affords -- see test_labels_fit_the_detail_column. The old
# "PARTLY SUNNY" was 45px against a 43px budget on stock settings, so the most
# common daytime sky on the panel rendered as "PARTLY SUN...". It was also
# wrong twice a day: this label is shown at night too.
LABELS = {
    "clear": "CLEAR", "partly": "PARTLY", "cloudy": "CLOUDY",
    "fog": "FOG", "drizzle": "DRIZZLE", "rain": "RAIN",
    "snow": "SNOW", "thunder": "STORMS",
}


def _maybe_float(value: object) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: object) -> int | None:
    v = _maybe_float(value)
    return None if v is None else int(round(v))


@dataclass
class DayForecast:
    date: str                 # ISO, so the scene can label it however it likes
    condition: str
    high: float
    low: float


@dataclass
class Weather:
    temperature: float
    feels_like: float
    high: float
    low: float
    condition: str
    is_day: bool
    unit: str = "F"
    precip_chance: int | None = None      # today's max probability, percent
    precip_now: float = 0.0               # falling right now, inches
    sunrise: datetime | None = None
    sunset: datetime | None = None
    wind: float | None = None             # sustained, in the configured unit
    gusts: float | None = None            # peak gust
    wind_dir: int | None = None           # degrees the wind is coming FROM
    wind_unit: str = "mph"
    aqi: int | None = None                # US AQI
    aqi_source: str = ""                  # "airnow" (measured) | "open-meteo" (modelled)
    aqi_station: str = ""
    forecast: list["DayForecast"] = field(default_factory=list)

    @property
    def label(self) -> str:
        return LABELS.get(self.condition, self.condition.upper())

    @property
    def aqi_band(self) -> tuple[str, str]:
        return aqi_band(self.aqi)

    @property
    def precip_text(self) -> str:
        """What is actually falling beats what might: if it is raining now,
        show the amount rather than a probability that has been overtaken."""
        # Below half a hundredth there is nothing to print: ".00IN" claims
        # rain and reports none in the same breath. Fall through to the
        # chance, which at least says something true.
        if self.precip_now >= 0.005:
            return f"{self.precip_now:.2f}IN".lstrip("0")
        if self.precip_chance is not None:
            return f"{self.precip_chance:.0f}%"
        return ""


class WeatherSource:
    def __init__(self, latitude: float | None, longitude: float | None,
                 cache_dir: Path, units: str = "fahrenheit",
                 refresh: int = 900, air_refresh: int = 3600,
                 timeout: float = 10.0,
                 tz: ZoneInfo | None = None, air_source: Any = None) -> None:
        # Open-Meteo is asked for timezone=auto, so sunrise and sunset arrive
        # as naive local times and need a zone attached to be comparable with
        # anything else.
        self.tz = tz or ZoneInfo("UTC")
        self.latitude = latitude
        self.longitude = longitude
        self.units = units
        self.refresh = refresh
        # Air quality is published hourly, which is the whole reason it is
        # cached apart from the forecast. It was then given the forecast's own
        # 15-minute clock, so the separate cache bought nothing and the second
        # endpoint was polled four times per new reading.
        self.air_refresh = air_refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "weather.json"
        self.air_cache_file = self.cache_dir / "air-quality.json"
        self.air_quality = True
        # Asked first when present; Open-Meteo's modelled figure is the
        # fallback. See sources/airquality.py for why measured wins.
        self.air_source = air_source
        self.last_error: str | None = None
        self._lock = threading.Lock()
        # `current()` runs twice per frame -- once to decide whether the scene
        # is in the rotation, once to draw it -- and each run re-reads and
        # re-parses two cache files. Holding the built value for a moment
        # collapses that pair. The window is far shorter than any refresh
        # interval, so it can never mask a fetch.
        self._memo: tuple[float, Weather | None] | None = None

    @property
    def configured(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def _age(self) -> float:
        if not self.cache_file.exists():
            return float("inf")
        return time.time() - self.cache_file.stat().st_mtime

    def _payload(self) -> dict | None:
        if not self.configured:
            return None
        with self._lock:
            if self._age() < self.refresh:
                try:
                    return json.loads(self.cache_file.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
            try:
                resp = httpx.get(ENDPOINT, timeout=self.timeout, params={
                    "latitude": self.latitude,
                    "longitude": self.longitude,
                    "current": "temperature_2m,apparent_temperature,weather_code,"
                               "is_day,precipitation,wind_speed_10m,"
                               "wind_gusts_10m,wind_direction_10m",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code,"
                             "precipitation_probability_max,sunrise,sunset",
                    "temperature_unit": self.units,
                    # Follow the temperature unit rather than adding a knob:
                    # somebody reading degrees F wants mph, not km/h.
                    "wind_speed_unit": "kmh" if self.units.startswith("c") else "mph",
                    "precipitation_unit": "inch",
                    "timezone": "auto",
                    # Today plus three: the strip has room for three columns.
                    "forecast_days": 4,
                })
                resp.raise_for_status()
                data = resp.json()
                if "current" not in data:
                    raise ValueError("no current conditions in response")
                self.cache_file.write_text(json.dumps(data))
                self.last_error = None
                return data
            except Exception as exc:  # noqa: BLE001 - stale beats blank
                self.last_error = f"{type(exc).__name__}: {exc}"
                if self.cache_file.exists():
                    try:
                        return json.loads(self.cache_file.read_text())
                    except (json.JSONDecodeError, OSError):
                        return None
                return None

    def _air(self) -> dict | None:
        """Air quality, cached separately. A failure here is not fatal -- the
        panel simply omits the AQI rather than losing the whole forecast."""
        if not (self.configured and self.air_quality):
            return None
        try:
            age = (time.time() - self.air_cache_file.stat().st_mtime
                   if self.air_cache_file.exists() else float("inf"))
            if age < self.air_refresh:
                return json.loads(self.air_cache_file.read_text())
            resp = httpx.get(AIR_ENDPOINT, timeout=self.timeout, params={
                "latitude": self.latitude, "longitude": self.longitude,
                "current": "us_aqi,pm2_5", "timezone": "auto",
            })
            resp.raise_for_status()
            data = resp.json()
            self.air_cache_file.write_text(json.dumps(data))
            return data
        except Exception:  # noqa: BLE001
            if self.air_cache_file.exists():
                try:
                    return json.loads(self.air_cache_file.read_text())
                except (json.JSONDecodeError, OSError):
                    return None
            return None

    MEMO_SECONDS = 2.0

    def current(self) -> Weather | None:
        if self._memo is not None and time.monotonic() - self._memo[0] < self.MEMO_SECONDS:
            return self._memo[1]
        value = self._build()
        self._memo = (time.monotonic(), value)
        return value

    def _build(self) -> Weather | None:
        data = self._payload()
        if not data:
            return None
        try:
            cur = data["current"]
            daily = data.get("daily", {})

            air = self._air() or {}
            aqi_raw = (air.get("current") or {}).get("us_aqi")
            aqi_source = "open-meteo" if aqi_raw is not None else ""
            aqi_station = ""
            if self.air_quality and self.air_source is not None:
                try:
                    measured = self.air_source.current()
                except Exception:  # noqa: BLE001 - the model is the fallback
                    measured = None
                if measured is not None:
                    aqi_raw = measured.aqi
                    aqi_source = measured.source
                    aqi_station = measured.station
            chance = (daily.get("precipitation_probability_max") or [None])[0]

            def when(key: str) -> datetime | None:
                values = daily.get(key) or []
                if not values:
                    return None
                try:
                    return datetime.fromisoformat(str(values[0])).replace(tzinfo=self.tz)
                except (ValueError, TypeError):
                    return None

            def first(key: str, fallback: float) -> float:
                """Today's value from the daily block, or the fallback.

                `daily` can carry a key with an empty list behind it, and
                indexing that raised straight past a perfectly good current
                temperature and blanked the whole panel.
                """
                values = daily.get(key) or []
                try:
                    return float(values[0])
                except (IndexError, TypeError, ValueError):
                    return float(fallback)

            days: list[DayForecast] = []
            times = daily.get("time") or []
            codes = daily.get("weather_code") or []
            highs = daily.get("temperature_2m_max") or []
            lows = daily.get("temperature_2m_min") or []
            for i in range(1, min(len(times), len(codes), len(highs), len(lows))):
                days.append(DayForecast(
                    date=str(times[i]),
                    condition=WMO.get(int(codes[i]), "cloudy"),
                    high=round(float(highs[i])),
                    low=round(float(lows[i])),
                ))

            return Weather(
                temperature=round(float(cur["temperature_2m"])),
                feels_like=round(float(cur.get("apparent_temperature", cur["temperature_2m"]))),
                high=round(first("temperature_2m_max", cur["temperature_2m"])),
                low=round(first("temperature_2m_min", cur["temperature_2m"])),
                condition=WMO.get(int(cur.get("weather_code", 0)), "cloudy"),
                is_day=bool(cur.get("is_day", 1)),
                unit="C" if self.units.startswith("c") else "F",
                precip_chance=None if chance is None else round(float(chance)),
                precip_now=float(cur.get("precipitation", 0) or 0),
                wind=_maybe_float(cur.get("wind_speed_10m")),
                gusts=_maybe_float(cur.get("wind_gusts_10m")),
                wind_dir=_maybe_int(cur.get("wind_direction_10m")),
                wind_unit="km/h" if self.units.startswith("c") else "mph",
                aqi=None if aqi_raw is None else round(float(aqi_raw)),
                aqi_source=aqi_source,
                aqi_station=aqi_station,
                forecast=days,
                sunrise=when("sunrise"),
                sunset=when("sunset"),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self.last_error = f"unexpected payload: {exc}"
            return None
