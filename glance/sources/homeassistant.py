"""Entity states from Home Assistant.

One call to /api/states fetches everything, which is cheaper than asking per
entity and — more usefully — lets the editor offer a dropdown of the entities
you actually have rather than making you type entity ids from memory.

An entity that is unavailable is reported as unavailable. Home Assistant says
"unavailable" and "unknown" explicitly, and passing that through beats
printing the last known value as though the sensor were still reporting.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

DEAD_STATES = {"unavailable", "unknown", "none", ""}

# device_class values worth colouring, and what "interesting" means for each.
ALERT_WHEN_ON = {
    "door", "window", "garage_door", "opening", "moisture", "smoke", "gas",
    "carbon_monoxide", "problem", "safety", "tamper",
}


@dataclass
class Entity:
    entity_id: str
    state: str
    name: str = ""
    unit: str = ""
    device_class: str = ""
    last_changed: datetime | None = None

    def since(self, now: datetime | None = None) -> float:
        """Seconds since this entity last changed state."""
        if self.last_changed is None:
            return float("inf")
        now = now or datetime.now(timezone.utc)
        return (now - self.last_changed).total_seconds()

    def ago(self, now: datetime | None = None) -> str:
        """How long ago, short enough for a panel."""
        seconds = self.since(now)
        if seconds == float("inf"):
            return "--"
        # Deliberately never "NOW": the scene uses that word for a zone that
        # is active *right now*, and two meanings for one word separated only
        # by colour is not a distinction a glance can make.
        if seconds < 90:
            return "1M"
        if seconds < 90 * 60:
            return f"{int(seconds // 60)}M"
        if seconds < 48 * 3600:
            return f"{int(seconds // 3600)}H"
        return f"{int(seconds // 86400)}D"

    @property
    def available(self) -> bool:
        return self.state.strip().lower() not in DEAD_STATES

    @property
    def numeric(self) -> float | None:
        try:
            return float(self.state)
        except (TypeError, ValueError):
            return None

    def display(self, decimals: int | None = None) -> str:
        """What to draw. Short, because a 64px column has no room for prose."""
        if not self.available:
            return "--"
        value = self.numeric
        if value is not None:
            if decimals is None:
                decimals = 0 if abs(value) >= 10 or value == int(value) else 1
            text = f"{value:.{decimals}f}"
            return f"{text}{self.unit}" if self.unit else text
        return self.state.replace("_", " ").upper()[:12]

    @property
    def alerting(self) -> bool:
        """Whether this state is the one you would want to notice."""
        if not self.available:
            return False
        state = self.state.lower()
        if self.device_class in ALERT_WHEN_ON:
            return state in ("on", "open", "detected", "wet", "unsafe")
        if self.device_class == "battery":
            value = self.numeric
            return value is not None and value <= 20
        return False


class HomeAssistantSource:
    def __init__(self, url: str = "", token: str = "",
                 cache_dir: Path | None = None, refresh: int = 60,
                 timeout: float = 8.0) -> None:
        self.url = str(url or "").rstrip("/")
        self.token = token or ""
        self.refresh = refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or ".")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "homeassistant.json"
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def _states(self) -> list[dict]:
        if not self.configured:
            self.last_error = "home assistant url or token not set"
            return []
        with self._lock:
            cached = None
            if self.cache_file.exists():
                try:
                    cached = json.loads(self.cache_file.read_text())
                    age = time.time() - self.cache_file.stat().st_mtime
                    if age < self.refresh:
                        return cached
                except (json.JSONDecodeError, OSError):
                    cached = None
            try:
                resp = httpx.get(
                    f"{self.url}/api/states", timeout=self.timeout,
                    headers={"Authorization": f"Bearer {self.token}",
                             "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    raise ValueError("unexpected response from /api/states")
                self.cache_file.write_text(json.dumps(data))
                self.last_error = None
                return data
            except Exception as exc:  # noqa: BLE001 - stale beats blank
                self.last_error = f"{type(exc).__name__}: {exc}"
                return cached or []

    @staticmethod
    def _entity(node: dict) -> Entity:
        attrs = node.get("attributes", {}) or {}
        changed = None
        raw = node.get("last_changed")
        if raw:
            try:
                changed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            except ValueError:
                changed = None
        return Entity(
            entity_id=str(node.get("entity_id", "")),
            state=str(node.get("state", "")),
            name=str(attrs.get("friendly_name") or node.get("entity_id", "")),
            unit=str(attrs.get("unit_of_measurement") or ""),
            device_class=str(attrs.get("device_class") or ""),
            last_changed=changed,
        )

    def all(self) -> list[Entity]:
        return [self._entity(n) for n in self._states()]

    def get(self, entity_id: str) -> Entity | None:
        wanted = entity_id.strip().lower()
        for node in self._states():
            if str(node.get("entity_id", "")).lower() == wanted:
                return self._entity(node)
        return None

    def pick(self, spec: str) -> list[tuple[Entity | None, str, str]]:
        """Resolve a config string into entities.

        Accepts `sensor.x, sensor.y` or `sensor.x=Label, sensor.y=Other`, so a
        long friendly_name can be shortened to something that fits 64px
        without renaming it in Home Assistant.
        """
        out: list[tuple[Entity | None, str, str]] = []
        for chunk in str(spec or "").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            entity_id, _, label = chunk.partition("=")
            entity_id = entity_id.strip()
            out.append((self.get(entity_id), entity_id, label.strip()))
        return out

    def of_class(self, device_class: str) -> list[Entity]:
        """Available entities of one device class, newest change first.

        Duplicates are common -- two integrations can expose the same camera --
        so unavailable copies are dropped rather than shown as gaps.
        """
        found = [e for e in self.all()
                 if e.device_class == device_class and e.available]
        return sorted(found, key=lambda e: e.since())

    def ids(self, prefixes: tuple[str, ...] = ()) -> list[str]:
        """Entity ids, for the editor's dropdown."""
        ids = sorted(str(n.get("entity_id", "")) for n in self._states())
        if prefixes:
            ids = [i for i in ids if i.startswith(prefixes)]
        return ids
