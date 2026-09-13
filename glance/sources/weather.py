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

LABELS = {
    "clear": "CLEAR", "partly": "PARTLY SUNNY", "cloudy": "CLOUDY",
    "fog": "FOG", "drizzle": "DRIZZLE", "rain": "RAIN",
    "snow": "SNOW", "thunder": "STORMS",
}


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
    aqi: int | None = None                # US AQI
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
        if self.precip_now > 0:
            return f"{self.precip_now:.2f}IN".lstrip("0")
        if self.precip_chance is not None:
            return f"{self.precip_chance:.0f}%"
        return ""


class WeatherSource:
    def __init__(self, latitude: float | None, longitude: float | None,
                 cache_dir: Path, units: str = "fahrenheit",
                 refresh: int = 900, timeout: float = 10.0,
                 tz: ZoneInfo | None = None) -> None:
        # Open-Meteo is asked for timezone=auto, so sunrise and sunset arrive
        # as naive local times and need a zone attached to be comparable with
        # anything else.
        self.tz = tz or ZoneInfo("UTC")
        self.latitude = latitude
        self.longitude = longitude
        self.units = units
        self.refresh = refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "weather.json"
        self.air_cache_file = self.cache_dir / "air-quality.json"
        self.air_quality = True
        self.last_error: str | None = None
        self._lock = threading.Lock()

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
                               "is_day,precipitation",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code,"
                             "precipitation_probability_max,sunrise,sunset",
                    "temperature_unit": self.units,
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
            if age < self.refresh:
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

    def current(self) -> Weather | None:
        data = self._payload()
        if not data:
            return None
        try:
            cur = data["current"]
            daily = data.get("daily", {})

            air = self._air() or {}
            aqi_raw = (air.get("current") or {}).get("us_aqi")
            chance = (daily.get("precipitation_probability_max") or [None])[0]

            def when(key: str) -> datetime | None:
                values = daily.get(key) or []
                if not values:
                    return None
                try:
                    return datetime.fromisoformat(str(values[0])).replace(tzinfo=self.tz)
                except (ValueError, TypeError):
                    return None

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
                high=round(float(daily.get("temperature_2m_max", [cur["temperature_2m"]])[0])),
                low=round(float(daily.get("temperature_2m_min", [cur["temperature_2m"]])[0])),
                condition=WMO.get(int(cur.get("weather_code", 0)), "cloudy"),
                is_day=bool(cur.get("is_day", 1)),
                unit="C" if self.units.startswith("c") else "F",
                precip_chance=None if chance is None else round(float(chance)),
                precip_now=float(cur.get("precipitation", 0) or 0),
                aqi=None if aqi_raw is None else round(float(aqi_raw)),
                forecast=days,
                sunrise=when("sunrise"),
                sunset=when("sunset"),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self.last_error = f"unexpected payload: {exc}"
            return None
