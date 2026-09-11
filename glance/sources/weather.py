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
from dataclasses import dataclass
from pathlib import Path

import httpx

ENDPOINT = "https://api.open-meteo.com/v1/forecast"

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
class Weather:
    temperature: float
    feels_like: float
    high: float
    low: float
    condition: str
    is_day: bool
    unit: str = "F"

    @property
    def label(self) -> str:
        return LABELS.get(self.condition, self.condition.upper())


class WeatherSource:
    def __init__(self, latitude: float | None, longitude: float | None,
                 cache_dir: Path, units: str = "fahrenheit",
                 refresh: int = 900, timeout: float = 10.0) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.units = units
        self.refresh = refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "weather.json"
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
                    "current": "temperature_2m,apparent_temperature,weather_code,is_day",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code",
                    "temperature_unit": self.units,
                    "timezone": "auto",
                    "forecast_days": 1,
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

    def current(self) -> Weather | None:
        data = self._payload()
        if not data:
            return None
        try:
            cur = data["current"]
            daily = data.get("daily", {})
            return Weather(
                temperature=round(float(cur["temperature_2m"])),
                feels_like=round(float(cur.get("apparent_temperature", cur["temperature_2m"]))),
                high=round(float(daily.get("temperature_2m_max", [cur["temperature_2m"]])[0])),
                low=round(float(daily.get("temperature_2m_min", [cur["temperature_2m"]])[0])),
                condition=WMO.get(int(cur.get("weather_code", 0)), "cloudy"),
                is_day=bool(cur.get("is_day", 1)),
                unit="C" if self.units.startswith("c") else "F",
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self.last_error = f"unexpected payload: {exc}"
            return None
