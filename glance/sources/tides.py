"""Tide predictions from NOAA CO-OPS.

No key and no account. NOAA publishes predictions for about 3,500 stations,
and asking for one is a single small request.

**Only the turning points are fetched.** Most stations are *subordinate*: their
tides are published as offsets from a reference station, and NOAA will give a
subordinate station its highs and lows but not a six-minute curve. The nearest
station to a house on the water is very often one of these -- Kayak Point, the
closest to Camano, is -- so asking for the curve would work for some addresses
and fail for the one that matters. The highs and lows work everywhere.

The water between them is drawn as half a cosine, which is the shape the rule
of twelfths approximates. It is within a few percent of the published curve
on an ordinary day; a tide table never claimed more precision than that for
a beach somewhere between two gauges anyway.

**Choosing a station.** Set `station` if you know the one you want. Without
it, the nearest prediction station to the weather coordinates is picked from
NOAA's own list. That list is two megabytes, so it is fetched once, kept as
the few fields that matter, and refreshed monthly.

Predictions are arithmetic, not observations: they do not change once
published. The cache is refreshed every few hours only so the window it
covers keeps moving forward with the clock.
"""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

DATAGETTER = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
STATIONS = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"

# A day behind and three ahead. Behind matters: the water right now sits
# between the last turn and the next, and the curve is drawn from before now.
BEHIND = timedelta(days=1)
RANGE_HOURS = 96

STATION_REFRESH = 30 * 86400


@dataclass
class TideEvent:
    when: datetime
    height: float
    kind: str                    # "H" | "L"

    @property
    def high(self) -> bool:
        return self.kind == "H"


@dataclass
class Tides:
    events: list[TideEvent]
    unit: str = "ft"
    station: str = ""
    station_name: str = ""
    distance_km: float | None = None

    def _bracket(self, at: datetime) -> tuple[TideEvent, TideEvent] | None:
        for before, after in zip(self.events, self.events[1:]):
            if before.when <= at <= after.when:
                return before, after
        return None

    def height_at(self, at: datetime) -> float | None:
        """The water at a moment, or None outside the predictions we hold."""
        pair = self._bracket(at)
        if pair is None:
            return None
        before, after = pair
        span = (after.when - before.when).total_seconds()
        if span <= 0:
            return before.height
        t = (at - before.when).total_seconds() / span
        return before.height + (after.height - before.height) * (1 - math.cos(math.pi * t)) / 2

    def rising(self, at: datetime) -> bool | None:
        """Whether the water is coming in. Heading for a high means it is."""
        pair = self._bracket(at)
        return None if pair is None else pair[1].high

    def upcoming(self, at: datetime, count: int = 2) -> list[TideEvent]:
        return [e for e in self.events if e.when > at][:count]

    def nearest(self, at: datetime) -> TideEvent | None:
        if not self.events:
            return None
        return min(self.events, key=lambda e: abs((e.when - at).total_seconds()))

    def day_range(self, day) -> tuple[TideEvent, TideEvent] | None:
        """The highest and lowest turns of a local day, past ones included.

        Taken from the turns rather than the curve: the water at midnight can
        sit above a small high, but nobody calls 11:59pm "the high tide".
        """
        turns = [e for e in self.events if e.when.date() == day]
        highs = [e for e in turns if e.high]
        lows = [e for e in turns if not e.high]
        if not highs or not lows:
            return None
        return max(highs, key=lambda e: e.height), min(lows, key=lambda e: e.height)


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    cosine = (math.sin(a) * math.sin(b)
              + math.cos(a) * math.cos(b) * math.cos(math.radians(lon2 - lon1)))
    return 6371.0 * math.acos(max(-1.0, min(1.0, cosine)))


def parse_predictions(rows: Any) -> list[TideEvent]:
    """NOAA's rows, asked for in GMT, as aware datetimes in time order."""
    out = []
    for row in rows or []:
        try:
            when = datetime.strptime(str(row["t"]), "%Y-%m-%d %H:%M")
            kind = str(row["type"]).upper()[:1]
            height = float(row["v"])
        except (KeyError, TypeError, ValueError):
            continue
        if kind in ("H", "L"):
            out.append(TideEvent(when.replace(tzinfo=timezone.utc), height, kind))
    return sorted(out, key=lambda e: e.when)


class TideSource:
    def __init__(self, cache_dir: Path, station: str = "",
                 latitude: float | None = None, longitude: float | None = None,
                 units: str = "english", refresh: int = 21600,
                 timeout: float = 10.0, tz: ZoneInfo | None = None) -> None:
        self.station = str(station or "").strip()
        self.latitude = latitude
        self.longitude = longitude
        self.units = "metric" if str(units).lower().startswith("m") else "english"
        self.refresh = refresh
        self.timeout = timeout
        self.tz = tz or ZoneInfo("UTC")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "tides.json"
        self.stations_file = self.cache_dir / "tide-stations.json"
        self.last_error: str | None = None
        self._lock = threading.Lock()
        # Asked twice per frame, as the weather is: once for the rotation and
        # once to draw.
        self._memo: tuple[float, Tides | None] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.station) or (self.latitude is not None
                                      and self.longitude is not None)

    # --- the station -------------------------------------------------------

    def _stations(self) -> list[dict]:
        cached = None
        if self.stations_file.exists():
            try:
                cached = json.loads(self.stations_file.read_text())
            except (json.JSONDecodeError, OSError):
                cached = None
            age = time.time() - self.stations_file.stat().st_mtime
            if cached and age < STATION_REFRESH:
                return cached
        try:
            resp = httpx.get(STATIONS, timeout=self.timeout,
                             params={"type": "tidepredictions"})
            resp.raise_for_status()
            # Keep the four fields that are used. The full record is two
            # megabytes of JSON, re-parsed on every refresh for no reason.
            slim = [{"id": str(s["id"]), "name": str(s.get("name", "")),
                     "lat": float(s["lat"]), "lng": float(s["lng"])}
                    for s in resp.json().get("stations", [])
                    if s.get("id") and s.get("lat") is not None]
            if not slim:
                raise ValueError("no stations in response")
            self.stations_file.write_text(json.dumps(slim))
            return slim
        except Exception as exc:  # noqa: BLE001 - a stale list is still a list
            self.last_error = f"stations: {type(exc).__name__}: {exc}"
            return cached or []

    def resolve_station(self) -> tuple[str, str, float | None] | None:
        """(id, name, km away). An explicit station wins over the nearest."""
        if self.station:
            return self.station, "", None
        if self.latitude is None or self.longitude is None:
            return None
        stations = self._stations()
        if not stations:
            return None
        here = (float(self.latitude), float(self.longitude))
        best = min(stations, key=lambda s: _km(*here, s["lat"], s["lng"]))
        return best["id"], best["name"], _km(*here, best["lat"], best["lng"])

    # --- predictions -------------------------------------------------------

    def _payload(self) -> dict | None:
        if not self.configured:
            return None
        with self._lock:
            cached = None
            if self.cache_file.exists():
                try:
                    cached = json.loads(self.cache_file.read_text())
                except (json.JSONDecodeError, OSError):
                    cached = None
                age = time.time() - self.cache_file.stat().st_mtime
                # A cache for another station or unit is somebody else's tide.
                fits = (cached and cached.get("units") == self.units
                        and (not self.station or cached.get("station") == self.station))
                if fits and age < self.refresh:
                    return cached
                if not fits:
                    cached = None
            try:
                found = self.resolve_station()
                if found is None:
                    raise ValueError(self.last_error or "no station")
                station, name, km = found
                begin = datetime.now(timezone.utc) - BEHIND
                resp = httpx.get(DATAGETTER, timeout=self.timeout, params={
                    "product": "predictions", "application": "glance-png-server",
                    "station": station, "datum": "MLLW", "interval": "hilo",
                    # GMT, then converted here. The station's own local time
                    # would be the panel's too, until somebody points a server
                    # in one zone at a beach in another.
                    "time_zone": "gmt", "units": self.units, "format": "json",
                    "begin_date": begin.strftime("%Y%m%d"), "range": RANGE_HOURS,
                })
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise ValueError(str(data["error"].get("message", "")).strip())
                if not data.get("predictions"):
                    raise ValueError("no predictions in response")
                payload = {"station": station, "name": name, "km": km,
                           "units": self.units, "predictions": data["predictions"]}
                self.cache_file.write_text(json.dumps(payload))
                self.last_error = None
                return payload
            except Exception as exc:  # noqa: BLE001 - stale beats blank
                self.last_error = f"{type(exc).__name__}: {exc}"
                return cached

    MEMO_SECONDS = 2.0

    def current(self) -> Tides | None:
        if self._memo is not None and time.monotonic() - self._memo[0] < self.MEMO_SECONDS:
            return self._memo[1]
        value = self._build()
        self._memo = (time.monotonic(), value)
        return value

    def _build(self) -> Tides | None:
        data = self._payload()
        if not data:
            return None
        events = parse_predictions(data.get("predictions"))
        if not events:
            return None
        for event in events:
            event.when = event.when.astimezone(self.tz)
        return Tides(events=events, unit="m" if data.get("units") == "metric" else "ft",
                     station=str(data.get("station", "")),
                     station_name=str(data.get("name", "")),
                     distance_km=data.get("km"))

    def status(self) -> dict[str, Any]:
        tides = self.current() if self.configured else None
        return {
            "configured": self.configured,
            "station": tides.station if tides else self.station,
            "name": tides.station_name if tides else "",
            "km": (round(tides.distance_km, 1)
                   if tides and tides.distance_km is not None else None),
            "last_error": self.last_error,
        }
