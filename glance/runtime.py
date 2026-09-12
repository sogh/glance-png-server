"""Wires configuration, data sources and the carousel into one object.

Everything stateful (HTTP caches, rotation position, parsed art) hangs off a
single GlanceApp so the server layer stays a thin adapter.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from . import brightness as brightness_mod
from .animation import Frames
from .canvas import Canvas
from .carousel import Carousel, Selection
from .config import ChannelEntry, Settings, load_settings
from .scenes import REGISTRY, RenderContext, error_canvas, resolve
from .scenes.static_image import list_static
from .sources.holidays import Holiday, active_holidays, load_holidays
from .sources.calendars import CalendarSet
from .sources.ics import CalendarSource
from .sources.instagram import InstagramSource
from .sources.weather import WeatherSource
from .sources.todos import TodoSource

log = logging.getLogger("glance")


class GlanceApp:
    def __init__(self, settings: Settings, config_path: Path | None = None) -> None:
        self.settings = settings
        self.config_path = Path(config_path) if config_path else None
        self._reload_lock = threading.Lock()
        self._mtimes: dict[str, float | None] = {}
        self._snapshot_mtimes()
        self.carousel = Carousel(settings)
        self.todos = TodoSource(settings.todos_file)
        self.calendars = CalendarSet(
            settings.calendars, settings.cache_dir, settings.tz, settings.ics_refresh
        )
        # Kept for scenes and callers that just want "the" calendar.
        first = next(iter(self.calendars.sources.values()), None)
        self.calendar: CalendarSource | None = self.calendars.get("default") or first
        self.brightness = brightness_mod.Brightness.from_config(settings.brightness)
        self.weather = self._build_weather(settings)
        self.instagram = self._build_instagram(settings)
        self._holidays: list[Holiday] = []
        self._holidays_mtime: float | None = None
        self._holiday_lock = threading.Lock()
        settings.static_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _build_weather(settings: Settings) -> WeatherSource:
        spec = settings.weather or {}

        def coord(key: str) -> float | None:
            raw = spec.get(key)
            try:
                return float(raw) if raw not in (None, "") else None
            except (TypeError, ValueError):
                return None

        source = WeatherSource(
            latitude=coord("latitude"),
            longitude=coord("longitude"),
            cache_dir=settings.cache_dir,
            units=str(spec.get("units", "fahrenheit")),
            refresh=int(spec.get("refresh", 900)),
        )
        source.air_quality = bool(spec.get("air_quality", True))
        return source

    @staticmethod
    def _build_instagram(settings: Settings) -> InstagramSource:
        spec = settings.instagram or {}
        return InstagramSource(
            token=str(spec.get("access_token", "") or ""),
            account=str(spec.get("account", "") or ""),
            user_id=str(spec.get("user_id", "me") or "me"),
            cache_dir=settings.cache_dir,
            refresh=int(spec.get("refresh", 3600)),
        )

    @classmethod
    def from_config(cls, path: str | Path | None = None) -> "GlanceApp":
        from .config import PROJECT_ROOT

        resolved = Path(path) if path else PROJECT_ROOT / "config" / "settings.yaml"
        return cls(load_settings(path), config_path=resolved)

    # --- live config -------------------------------------------------------

    def _watched(self) -> dict[str, Path]:
        paths = {"overlay": Path(self.settings.overlay_file)}
        if self.config_path:
            paths["config"] = self.config_path
        return paths

    def _snapshot_mtimes(self) -> None:
        self._mtimes = {
            k: (p.stat().st_mtime if p.exists() else None)
            for k, p in self._watched().items()
        }

    def reload_if_changed(self) -> bool:
        """Re-read settings.yaml and the overlay when either has changed.

        Editing the carousel should take effect on the panel's next fetch, not
        on the next redeploy.
        """
        if self.config_path is None:
            # Constructed from a Settings object with no file behind it; there
            # is nothing to re-read, and guessing a path would silently load
            # somebody else's config.
            return False
        with self._reload_lock:
            current = {
                k: (p.stat().st_mtime if p.exists() else None)
                for k, p in self._watched().items()
            }
            if current == self._mtimes:
                return False
            try:
                fresh = load_settings(self.config_path)
            except Exception as exc:  # noqa: BLE001 - keep serving the old config
                log.warning("config reload failed, keeping previous: %s", exc)
                self._mtimes = current
                return False

            calendars_changed = fresh.calendars != self.settings.calendars
            weather_changed = fresh.weather != self.settings.weather
            instagram_changed = fresh.instagram != self.settings.instagram
            self.settings = fresh
            self.brightness = brightness_mod.Brightness.from_config(fresh.brightness)
            if weather_changed:
                self.weather = self._build_weather(fresh)
            if instagram_changed:
                self.instagram = self._build_instagram(fresh)
            self.carousel.settings = fresh
            self.carousel.min_advance_interval = fresh.carousel_min_advance
            self.todos.path = Path(fresh.todos_file)
            if calendars_changed:
                self.calendars = CalendarSet(
                    fresh.calendars, fresh.cache_dir, fresh.tz, fresh.ics_refresh
                )
                first = next(iter(self.calendars.sources.values()), None)
                self.calendar = self.calendars.get("default") or first
            self._mtimes = current
            log.info("config reloaded")
            return True

    # --- the overlay the editor writes -------------------------------------

    def read_overlay(self) -> dict[str, Any]:
        path = Path(self.settings.overlay_file)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def write_overlay(self, overlay: dict[str, Any]) -> None:
        path = Path(self.settings.overlay_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(overlay, indent=2, sort_keys=True))
        tmp.replace(path)          # atomic: never leave a half-written overlay
        self.reload_if_changed()

    def set_channel(self, name: str, entries: list[dict[str, Any]]) -> None:
        overlay = self.read_overlay()
        overlay.setdefault("channels", {})[name] = entries
        self.write_overlay(overlay)

    def reset_channel(self, name: str) -> None:
        """Forget the overlay for one channel, restoring settings.yaml."""
        overlay = self.read_overlay()
        overlay.get("channels", {}).pop(name, None)
        if not overlay.get("channels"):
            overlay.pop("channels", None)
        self.write_overlay(overlay)

    def set_carousel(self, values: dict[str, Any]) -> None:
        overlay = self.read_overlay()
        overlay.setdefault("carousel", {}).update(values)
        self.write_overlay(overlay)

    def channel_spec(self, name: str) -> list[dict[str, Any]]:
        """The channel as data, ready for the editor."""
        return [
            {
                "ref": e.ref,
                "params": e.params,
                "enabled": e.enabled,
                "takeover": e.takeover,
                "dwell": e.dwell,
                "when": e.when,
            }
            for e in self.settings.channels.get(name, [])
        ]

    # --- holidays reload on edit ------------------------------------------

    @property
    def holidays(self) -> list[Holiday]:
        path = self.settings.holidays_file
        with self._holiday_lock:
            mtime = path.stat().st_mtime if path.exists() else None
            if mtime != self._holidays_mtime:
                try:
                    self._holidays = load_holidays(path)
                    self._holidays_mtime = mtime
                except Exception as exc:  # noqa: BLE001 - keep the last good list
                    log.warning("holidays reload failed: %s", exc)
            return self._holidays

    # --- rendering ---------------------------------------------------------

    def dim(self, rendered: Canvas | Frames, ctx: RenderContext) -> Canvas | Frames:
        """Apply the time-of-day level to a finished render.

        Done here rather than in each scene so every panel is treated the
        same, including artwork loaded from a file.
        """
        level = ctx.brightness if ctx.brightness is not None else \
            self.brightness.level_at(ctx.now)
        for canvas in getattr(rendered, "canvases", [rendered]):
            brightness_mod.apply(canvas, level)
        return rendered

    def context(self, now: datetime | None = None,
                width: int | None = None,
                brightness: float | None = None) -> RenderContext:
        self.reload_if_changed()
        return RenderContext(
            brightness=brightness,
            settings=self.settings,
            now=now or datetime.now(self.settings.tz),
            width_override=width,
            calendar=self.calendar,
            calendars=self.calendars,
            weather=self.weather,
            instagram=self.instagram,
            todos=self.todos,
            holidays=self.holidays,
        )

    def render_scene(self, ref: str, params: dict[str, Any] | None = None,
                     ctx: RenderContext | None = None,
                     width: int | None = None,
                     brightness: float | None = None) -> tuple[Canvas | Frames, str]:
        """Render one scene by reference. Returns (canvas, label).

        Failures are drawn, not raised: the device caches the last image it
        fetched, so a 500 looks exactly like a working panel.
        """
        ctx = ctx or self.context(width=width, brightness=brightness)
        scene, merged = resolve(ref, params)
        if scene is None:
            return error_canvas(ctx, f"unknown scene {ref}", "404"), f"missing:{ref}"
        try:
            return self.dim(scene.render(ctx, merged), ctx), ref
        except Exception as exc:  # noqa: BLE001
            log.exception("scene %s failed", ref)
            return error_canvas(ctx, f"{type(exc).__name__}: {exc}", ref[:12].upper()), f"error:{ref}"

    def render_channel(self, channel: str, advance: bool = True,
                       now: datetime | None = None,
                       width: int | None = None,
                       brightness: float | None = None) -> tuple[Canvas | Frames, Selection | None, str]:
        ctx = self.context(now, width=width, brightness=brightness)
        if channel not in self.settings.channels:
            known = ", ".join(self.settings.channels) or "none configured"
            return error_canvas(ctx, f"channels: {known}", "NO CHANNEL"), None, "unknown-channel"

        selection = self.carousel.select(channel, ctx, advance=advance)
        if selection is None:
            fallback = self.settings.raw.get("fallback", {}) or {}
            ref = str(fallback.get("scene", "clock"))
            canvas, label = self.render_scene(ref, fallback.get("params", {}), ctx)
            return canvas, None, f"fallback:{label}"

        try:
            rendered = self.dim(selection.scene.render(ctx, selection.params), ctx)
            return rendered, selection, selection.key
        except Exception as exc:  # noqa: BLE001
            log.exception("scene %s failed in channel %s", selection.key, channel)
            return (
                error_canvas(ctx, f"{type(exc).__name__}: {exc}", selection.entry.ref[:12].upper()),
                selection,
                f"error:{selection.key}",
            )

    def png(self, canvas: Canvas | Frames) -> bytes:
        # Canvas and Frames both expose to_png(); Frames returns APNG bytes
        # when it holds more than one frame.
        return canvas.to_png(quantize=self.settings.quantize_png)

    # --- introspection -----------------------------------------------------

    def status(self) -> dict[str, Any]:
        ctx = self.context()
        channels: dict[str, Any] = {}
        for name in self.settings.channels:
            cands = self.carousel.candidates(name, ctx)
            channels[name] = {
                "configured": len(self.settings.channels[name]),
                "available": [s.key for s in cands],
                "takeover": [s.key for s in cands if s.takeover],
                "state": self.carousel.state_for(name),
            }
        return {
            "now": ctx.now.isoformat(),
            "panel": {
                "width": self.settings.width,
                "height": 32,
                "brightness": round(self.brightness.level_at(ctx.now), 3),
            },
            "carousel": {
                "mode": self.settings.carousel_mode,
                "dwell": self.settings.carousel_dwell,
            },
            "channels": channels,
            "scenes": sorted(REGISTRY),
            "static_images": list_static(ctx),
            "holidays": {
                "loaded": len(self.holidays),
                "active": [
                    {"name": h.name, "slug": h.slug, "days_away": d}
                    for h, d in active_holidays(self.holidays, ctx.today)
                ],
            },
            "sources": {
                "calendars": self.calendars.status(ctx.now),
                "weather": {
                    "configured": self.weather.configured,
                    "last_error": self.weather.last_error,
                },
                "instagram": {
                    "configured": self.instagram.configured,
                    "account": self.instagram.account or "me",
                    "last_error": self.instagram.last_error,
                },
                "todos": {
                    "path": str(self.settings.todos_file),
                    "last_error": self.todos.last_error,
                    "open": len(self.todos.open_items(ctx.today)),
                },
            },
        }
