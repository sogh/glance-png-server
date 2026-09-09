"""Wires configuration, data sources and the carousel into one object.

Everything stateful (HTTP caches, rotation position, parsed art) hangs off a
single GlanceApp so the server layer stays a thin adapter.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .animation import Frames
from .canvas import Canvas
from .carousel import Carousel, Selection
from .config import Settings, load_settings
from .scenes import REGISTRY, RenderContext, error_canvas, resolve
from .scenes.static_image import list_static
from .sources.holidays import Holiday, active_holidays, load_holidays
from .sources.calendars import CalendarSet
from .sources.ics import CalendarSource
from .sources.todos import TodoSource

log = logging.getLogger("glance")


class GlanceApp:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.carousel = Carousel(settings)
        self.todos = TodoSource(settings.todos_file)
        self.calendars = CalendarSet(
            settings.calendars, settings.cache_dir, settings.tz, settings.ics_refresh
        )
        # Kept for scenes and callers that just want "the" calendar.
        first = next(iter(self.calendars.sources.values()), None)
        self.calendar: CalendarSource | None = self.calendars.get("default") or first
        self._holidays: list[Holiday] = []
        self._holidays_mtime: float | None = None
        self._holiday_lock = threading.Lock()
        settings.static_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, path: str | Path | None = None) -> "GlanceApp":
        return cls(load_settings(path))

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

    def context(self, now: datetime | None = None) -> RenderContext:
        return RenderContext(
            settings=self.settings,
            now=now or datetime.now(self.settings.tz),
            calendar=self.calendar,
            calendars=self.calendars,
            todos=self.todos,
            holidays=self.holidays,
        )

    def render_scene(self, ref: str, params: dict[str, Any] | None = None,
                     ctx: RenderContext | None = None) -> tuple[Canvas | Frames, str]:
        """Render one scene by reference. Returns (canvas, label).

        Failures are drawn, not raised: the device caches the last image it
        fetched, so a 500 looks exactly like a working panel.
        """
        ctx = ctx or self.context()
        scene, merged = resolve(ref, params)
        if scene is None:
            return error_canvas(ctx, f"unknown scene {ref}", "404"), f"missing:{ref}"
        try:
            return scene.render(ctx, merged), ref
        except Exception as exc:  # noqa: BLE001
            log.exception("scene %s failed", ref)
            return error_canvas(ctx, f"{type(exc).__name__}: {exc}", ref[:12].upper()), f"error:{ref}"

    def render_channel(self, channel: str, advance: bool = True,
                       now: datetime | None = None) -> tuple[Canvas | Frames, Selection | None, str]:
        ctx = self.context(now)
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
            return selection.scene.render(ctx, selection.params), selection, selection.key
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
            "panel": {"width": self.settings.width, "height": 32},
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
                "todos": {
                    "path": str(self.settings.todos_file),
                    "last_error": self.todos.last_error,
                    "open": len(self.todos.open_items(ctx.today)),
                },
            },
        }
