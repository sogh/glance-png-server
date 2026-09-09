"""Configuration loading: settings.yaml + environment expansion."""

from __future__ import annotations

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
    access_token: str = ""                    # when set, image routes require it
    carousel_mode: str = "advance"            # "advance" | "clock"
    carousel_dwell: int = 300                 # seconds, clock mode only
    carousel_min_advance: float = 30.0        # debounce, advance mode only
    state_file: Path = PROJECT_ROOT / "data" / "state.json"
    static_dir: Path = PROJECT_ROOT / "assets" / "static"
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    holidays_file: Path = PROJECT_ROOT / "config" / "holidays.yaml"
    todos_file: Path = PROJECT_ROOT / "data" / "reminders.json"
    ics_url: str = ""
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
    else:
        raise ValueError(f"channel entry needs a 'scene' or 'static' key: {item!r}")

    return ChannelEntry(
        ref=ref,
        takeover=bool(data.pop("takeover", False)),
        when=data.pop("when", {}) or {},
        enabled=bool(data.pop("enabled", True)),
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
    todos = src.get("reminders", src.get("todos", {})) or {}
    paths = raw.get("paths", {}) or {}

    s = Settings(
        width=int(panel.get("width", 192)),
        host=str(server.get("host", "0.0.0.0")),
        port=int(server.get("port", 8080)),
        timezone=str(raw.get("timezone", "UTC")),
        quantize_png=bool(panel.get("quantize_png", True)),
        access_token=str(server.get("access_token", "") or ""),
        carousel_mode=str(car.get("mode", "advance")),
        carousel_dwell=int(car.get("dwell", 300)),
        carousel_min_advance=float(car.get("min_advance_interval", 30)),
        ics_url=str(cal.get("ics_url", "") or ""),
        ics_refresh=int(cal.get("refresh", 900)),
        ics_lookahead_days=int(cal.get("lookahead_days", 14)),
        raw=raw,
    )

    for attr, key in (
        ("state_file", "state_file"),
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
    if s.carousel_mode not in ("advance", "clock"):
        raise ValueError(f"carousel.mode must be 'advance' or 'clock', got {s.carousel_mode!r}")
    return s
