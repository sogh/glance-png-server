"""Air quality from a monitor, falling back to a model.

Open-Meteo's `us_aqi` is derived from the CAMS atmospheric model on a coarse
grid -- ask for a point on Camano Island and it answers from a cell some
kilometres away, roughly 11km across. It is an estimate of the air over the
region, not a reading from anywhere in particular, and on this stretch of
Puget Sound it runs high: 53 against the 41 the nearest instrument reported at
the same hour. Twelve points is cosmetic, but it moved the panel from "Good"
to "Moderate", which is the part anybody actually reads.

So ask EPA AirNow first, which publishes what the monitors measured, and keep
the model as the fallback. Two ways in:

  **The official API**, `airnowapi.org`, needs a free key. Documented, stable,
  and what you should use if you are going to depend on this.

  **The reporting-area endpoint** behind airnow.gov needs no key. Undocumented
  and therefore liable to change without notice -- the same bet this project
  already takes on ESPN's scores API. It is the default because it works with
  no signup.

A reading carries where it came from, because "53 from a model" and "41 from a
monitor thirteen kilometres away" are different claims and the panel should be
able to say which it is making.

**On combining pollutants.** The EPA's AQI is the worst of them, and the
keyless endpoint obliges by returning the closest reading *for each pollutant
separately* -- which on Camano means PM2.5 from a monitor 13km away, PM10 from
one 27km away, and ozone from one 47km away. Taking the plain maximum of those
is how an ozone reading from another county ends up describing your garden. So
only monitors within `max_distance` are considered, and the worst pollutant
among those wins. Distance first, then the EPA rule.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

REPORTING_AREA = "https://airnowgovapi.com/reportingarea/get"
OFFICIAL = "https://www.airnowapi.org/aq/observation/latLong/current/"

# Beyond this, a monitor is measuring somebody else's air. The nearest station
# to a rural address is routinely 10-15km off, so the limit has to clear that
# while still excluding the next county.
DEFAULT_MAX_DISTANCE_KM = 25.0


@dataclass
class Reading:
    aqi: int
    source: str                  # "airnow" | "open-meteo"
    pollutant: str = ""
    station: str = ""
    observed: str = ""           # as the provider words it
    distance_km: float | None = None

    @property
    def measured(self) -> bool:
        """Whether an instrument produced this, or a model did."""
        return self.source == "airnow"


def _int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    # AirNow uses -1 for "no reading", which is not an AQI of minus one.
    return number if number >= 0 else None


class AirNowSource:
    def __init__(self, latitude: float | None, longitude: float | None,
                 cache_dir: Path, api_key: str = "", refresh: int = 900,
                 timeout: float = 10.0, distance: int = 50,
                 max_distance: float = DEFAULT_MAX_DISTANCE_KM) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self.api_key = str(api_key or "").strip()
        self.refresh = refresh
        self.timeout = timeout
        self.distance = distance
        self.max_distance = float(max_distance)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "airnow.json"
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return self.latitude is not None and self.longitude is not None

    def _fetch(self) -> Any:
        if self.api_key:
            resp = httpx.get(OFFICIAL, timeout=self.timeout, params={
                "format": "application/json",
                "latitude": self.latitude, "longitude": self.longitude,
                "distance": self.distance, "API_KEY": self.api_key,
            })
        else:
            resp = httpx.get(REPORTING_AREA, timeout=self.timeout, params={
                "latitude": self.latitude, "longitude": self.longitude,
            })
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            raise ValueError("expected a list of observations")
        return data

    def _payload(self) -> Any:
        with self._lock:
            cached = None
            if self.cache_file.exists():
                try:
                    cached = json.loads(self.cache_file.read_text())
                except (json.JSONDecodeError, OSError):
                    cached = None
                age = time.time() - self.cache_file.stat().st_mtime
                if cached is not None and age < self.refresh:
                    return cached
            try:
                data = self._fetch()
                self.cache_file.write_text(json.dumps(data))
                self.last_error = None
                return data
            except Exception as exc:  # noqa: BLE001 - the model is the fallback
                self.last_error = f"{type(exc).__name__}: {exc}"
                return cached

    def _distance_to(self, row: dict) -> float | None:
        """Great-circle km from here to a row's monitor, if it says where it is."""
        lat = row.get("latitude", row.get("Latitude"))
        lon = row.get("longitude", row.get("Longitude"))
        try:
            lat, lon = float(lat), float(lon)
            here_lat, here_lon = float(self.latitude), float(self.longitude)
        except (TypeError, ValueError):
            return None
        if not (lat or lon):
            return None
        a, b = math.radians(here_lat), math.radians(lat)
        cosine = (math.sin(a) * math.sin(b)
                  + math.cos(a) * math.cos(b) * math.cos(math.radians(lon - here_lon)))
        return 6371.0 * math.acos(max(-1.0, min(1.0, cosine)))

    def readings(self) -> list[Reading]:
        """Every usable row, nearest first."""
        if not self.configured:
            self.last_error = "no coordinates"
            return []
        out: list[Reading] = []
        for row in self._payload() or []:
            if not isinstance(row, dict):
                continue
            aqi = _int(row.get("aqi", row.get("AQI")))
            if aqi is None:
                continue
            observed = " ".join(str(x) for x in (
                row.get("validDate") or row.get("DateObserved") or "",
                row.get("time") or row.get("HourObserved") or "",
                row.get("timezone") or row.get("LocalTimeZone") or "") if x).strip()
            out.append(Reading(
                aqi=aqi, source="airnow",
                pollutant=str(row.get("parameter") or row.get("ParameterName") or ""),
                station=str(row.get("siteName") or row.get("ReportingArea")
                            or row.get("reportingArea") or ""),
                observed=observed,
                distance_km=self._distance_to(row),
            ))
        return sorted(out, key=lambda r: (r.distance_km is None, r.distance_km or 0))

    def current(self) -> Reading | None:
        """The worst pollutant among the monitors near enough to matter.

        Distance is applied before the EPA's worst-of rule, or an ozone
        reading from the next county describes your garden.
        """
        near = [r for r in self.readings()
                if r.distance_km is None or r.distance_km <= self.max_distance]
        if not near:
            # Nothing close enough. Better to say nothing and let the model
            # answer than to report another county's air as this one's.
            return None
        return max(near, key=lambda r: r.aqi)

    def status(self) -> dict[str, Any]:
        reading = self.current() if self.configured else None
        return {
            "configured": self.configured,
            "keyed": bool(self.api_key),
            "max_distance_km": self.max_distance,
            "last_error": self.last_error,
            "reading": None if reading is None else {
                "aqi": reading.aqi, "pollutant": reading.pollutant,
                "station": reading.station,
                "km": None if reading.distance_km is None else round(reading.distance_km, 1),
                "observed": reading.observed,
            },
        }
