"""Several named calendars, each with its own default styling.

One calendar per purpose reads better than one calendar with everything in
it: an agenda feed, a reminders feed, a holidays/events feed. Each gets
default colours in config, and individual entries can override them with
tags -- see sources/tags.py.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .ics import CalendarSource, Event
from .tags import Style


class CalendarSet:
    """A named collection of ICS feeds."""

    def __init__(
        self,
        specs: dict[str, dict[str, Any]],
        cache_dir: Path,
        tz: ZoneInfo,
        default_refresh: int = 900,
    ) -> None:
        self.sources: dict[str, CalendarSource] = {}
        for name, spec in (specs or {}).items():
            url = str((spec or {}).get("url", "") or "")
            if not url:
                continue          # declared but not configured yet
            self.sources[name] = CalendarSource(
                url=url,
                cache_dir=cache_dir,
                tz=tz,
                refresh=int(spec.get("refresh", default_refresh)),
                name=name,
                default_style=Style(
                    color=spec.get("color"),
                    accent=spec.get("accent"),
                    style=spec.get("style"),
                    priority=spec.get("priority"),
                ),
            )

    def __bool__(self) -> bool:
        return bool(self.sources)

    def __contains__(self, name: str) -> bool:
        return name in self.sources

    @property
    def names(self) -> list[str]:
        return list(self.sources)

    def get(self, name: str) -> CalendarSource | None:
        return self.sources.get(name)

    def _selected(self, names: str | Iterable[str] | None) -> list[CalendarSource]:
        if names is None:
            return list(self.sources.values())
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",") if n.strip()]
        return [self.sources[n] for n in names if n in self.sources]

    def upcoming(
        self,
        now: datetime,
        names: str | Iterable[str] | None = None,
        lookahead_days: int = 14,
        include_current: bool = True,
    ) -> list[Event]:
        """Events from the selected calendars, merged and in time order."""
        merged: list[Event] = []
        for src in self._selected(names):
            merged.extend(src.upcoming(now, lookahead_days, include_current))
        return sorted(merged, key=lambda e: e.start)

    def errors(self) -> dict[str, str]:
        return {n: s.last_error for n, s in self.sources.items() if s.last_error}

    def status(self, now: datetime) -> dict[str, Any]:
        return {
            name: {
                "upcoming": len(src.upcoming(now)),
                "last_error": src.last_error,
            }
            for name, src in self.sources.items()
        }
