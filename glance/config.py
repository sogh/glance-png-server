"""Configuration loading: settings.yaml + environment expansion."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    """Recursively expand ${VAR} and ${VAR:-default} in strings."""
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), m.group(2) or "")
        return _ENV_PATTERN.sub(sub, value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


@dataclass
class ChannelEntry:
    """One slot in a channel's rotation."""

    ref: str                                  # "agenda", "todos", "static:winter"
    params: dict[str, Any] = field(default_factory=dict)
    takeover: bool = False                    # pre-empts rotation while available
    when: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    dwell: float = 0.0                        # seconds to hold before advancing

    @property
    def key(self) -> str:
        """Stable identity for rotation state, so reordering a channel does not
        silently resume mid-list on the wrong scene."""
        if not self.params:
            return self.ref
        bits = ",".join(f"{k}={self.params[k]}" for k in sorted(self.params))
        return f"{self.ref}({bits})"


@dataclass
class Settings:
    width: int = 192
    host: str = "0.0.0.0"
    port: int = 8080
    timezone: str = "UTC"
    quantize_png: bool = True
    brightness: Any = None                    # panel.brightness, see brightness.py
    access_token: str = ""                    # when set, image routes require it
    carousel_mode: str = "advance"            # "advance" | "clock"
    carousel_dwell: int = 300                 # seconds, clock mode only
    carousel_min_advance: float = 30.0        # debounce, advance mode only
    state_file: Path = PROJECT_ROOT / "data" / "state.json"
    overlay_file: Path = PROJECT_ROOT / "data" / "overrides.json"
    static_dir: Path = PROJECT_ROOT / "assets" / "static"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    holidays_file: Path = PROJECT_ROOT / "config" / "holidays.yaml"
    todos_file: Path = PROJECT_ROOT / "data" / "reminders.json"
    ics_url: str = ""                          # legacy single-calendar form
    calendars: dict[str, Any] = field(default_factory=dict)
    ics_refresh: int = 900
    ics_lookahead_days: int = 14
    channels: dict[str, list[ChannelEntry]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def resolve(self, value: str | Path) -> Path:
        p = Path(value)
        return p if p.is_absolute() else PROJECT_ROOT / p


def _parse_entry(item: Any) -> ChannelEntry:
    if isinstance(item, str):
        return ChannelEntry(ref=item)
    if not isinstance(item, dict):
        raise ValueError(f"channel entry must be a string or mapping, got {item!r}")

    data = dict(item)
    if "static" in data:
        ref = f"static:{data.pop('static')}"
    elif "scene" in data:
        ref = str(data.pop("scene"))
    elif "ref" in data:
        # The form channel_spec() emits, so the editor can round-trip a
        # channel through the overlay without translating key names.
        ref = str(data.pop("ref"))
    else:
        raise ValueError(f"channel entry needs a 'scene', 'static' or 'ref' key: {item!r}")

    return ChannelEntry(
        ref=ref,
        takeover=bool(data.pop("takeover", False)),
        when=data.pop("when", {}) or {},
        enabled=bool(data.pop("enabled", True)),
        dwell=float(data.pop("dwell", 0) or 0),
        params=data.pop("params", {}) or data,  # leftover keys are scene params
    )


def load_settings(path: str | Path | None = None) -> Settings:
    cfg_path = Path(path) if path else PROJECT_ROOT / "config" / "settings.yaml"
    raw: dict[str, Any] = {}
    if cfg_path.exists():
        raw = _expand(yaml.safe_load(cfg_path.read_text()) or {})

    panel = raw.get("panel", {}) or {}
    server = raw.get("server", {}) or {}
    car = raw.get("carousel", {}) or {}
    src = raw.get("sources", {}) or {}
    cal = src.get("calendar", {}) or {}
    # "reminders" is the name in the config; "todos" is kept working so an
    # existing settings.yaml does not break.
    todos = src.get("reminders_file", src.get("reminders", src.get("todos", {}))) or {}
    paths = raw.get("paths", {}) or {}

    s = Settings(
        width=int(panel.get("width", 192)),
        host=str(server.get("host", "0.0.0.0")),
        port=int(server.get("port", 8080)),
        timezone=str(raw.get("timezone", "UTC")),
        quantize_png=bool(panel.get("quantize_png", True)),
        brightness=panel.get("brightness"),
        access_token=str(server.get("access_token", "") or ""),
        carousel_mode=str(car.get("mode", "advance")),
        carousel_dwell=int(car.get("dwell", 300)),
        carousel_min_advance=float(car.get("min_advance_interval", 30)),
        ics_url=str(cal.get("ics_url", "") or ""),
        ics_refresh=int(src.get("refresh", cal.get("refresh", 900))),
        calendars=dict(src.get("calendars", {}) or {}),
        ics_lookahead_days=int(src.get("lookahead_days", cal.get("lookahead_days", 14))),
        raw=raw,
    )

    for attr, key in (
        ("state_file", "state_file"),
        ("overlay_file", "overlay_file"),
        ("static_dir", "static_dir"),
        ("cache_dir", "cache_dir"),
        ("holidays_file", "holidays_file"),
    ):
        if key in paths:
            setattr(s, attr, s.resolve(paths[key]))
    if "path" in todos:
        s.todos_file = s.resolve(todos["path"])

    s.channels = {
        name: [_parse_entry(i) for i in (entries or [])]
        for name, entries in (raw.get("channels", {}) or {}).items()
    }
    # A single `sources.calendar.ics_url` still works; it becomes a calendar
    # named "default" so everything downstream sees one shape.
    if s.ics_url and "default" not in s.calendars:
        s.calendars["default"] = {"url": s.ics_url, "refresh": s.ics_refresh}

    apply_overlay(s)

    if s.carousel_mode not in ("advance", "clock"):
        raise ValueError(f"carousel.mode must be 'advance' or 'clock', got {s.carousel_mode!r}")
    return s


def apply_overlay(s: Settings) -> None:
    """Layer data/overrides.json on top of the parsed settings.

    The editor writes only here, never back to settings.yaml. That file is
    hand-authored with comments explaining why things are the way they are;
    round-tripping YAML through a form destroys those and guarantees conflicts
    with the repo. Keeping edits in a separate JSON file means the config stays
    pristine, "reset to file" is deleting a key, and a deploy never clobbers
    what you changed from the UI (data/ is excluded from deploys).

    A channel present in the overlay REPLACES that channel wholesale rather
    than merging entry by entry -- the editor always sends the full list, and
    merging arrays by index is a reliable source of surprises.
    """
    path = Path(s.overlay_file)
    if not path.exists():
        return
    try:
        overlay = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return          # a corrupt overlay must not take the panel down

    car = overlay.get("carousel", {}) or {}
    if "mode" in car:
        s.carousel_mode = str(car["mode"])
    if "dwell" in car:
        s.carousel_dwell = int(car["dwell"])
    if "min_advance_interval" in car:
        s.carousel_min_advance = float(car["min_advance_interval"])

    for name, entries in (overlay.get("channels", {}) or {}).items():
        s.channels[name] = [_parse_entry(i) for i in (entries or [])]
