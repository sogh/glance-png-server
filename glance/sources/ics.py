"""Google Calendar (or any ICS publisher) as an event source.

Fetches the secret .ics URL on a timer, caches the raw text to disk, and
expands recurrence rules locally. The disk cache is deliberately also a
fallback: if the fetch fails, we serve stale events rather than letting the
panel go blank over a transient network blip.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from .tags import Style, style_for

USER_AGENT = "glance-png-server/1.0 (+https://glance-led.dev)"


@dataclass
class Event:
    summary: str                     # tags stripped; what actually gets drawn
    start: datetime
    end: datetime
    all_day: bool
    location: str = ""
    raw_summary: str = ""            # exactly as typed in the calendar
    style: Style = field(default_factory=Style)
    calendar: str = ""               # which configured calendar it came from

    def starts_in(self, now: datetime) -> timedelta:
        return self.start - now

    def is_now(self, now: datetime) -> bool:
        return self.start <= now < self.end


class CalendarSource:
    def __init__(
        self,
        url: str,
        cache_dir: Path,
        tz: ZoneInfo,
        refresh: int = 900,
        timeout: float = 10.0,
        name: str = "",
        default_style: Style | None = None,
        mode_words: frozenset[str] = frozenset(),
    ) -> None:
        self.url = url
        self.name = name
        self.mode_words = mode_words
        self.default_style = default_style or Style()
        self.tz = tz
        self.refresh = refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(url.encode()).hexdigest()[:16] if url else "none"
        self.cache_file = self.cache_dir / f"calendar-{digest}.ics"
        self.last_error: str | None = None
        self._lock = threading.Lock()

    # --- fetching ----------------------------------------------------------

    def _cache_age(self) -> float:
        if not self.cache_file.exists():
            return float("inf")
        return time.time() - self.cache_file.stat().st_mtime

    def raw_ics(self, force: bool = False) -> str | None:
        if not self.url:
            return None
        with self._lock:
            if not force and self._cache_age() < self.refresh:
                return self.cache_file.read_text()
            try:
                resp = httpx.get(
                    self.url,
                    timeout=self.timeout,
                    follow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                )
                resp.raise_for_status()
                text = resp.text
                if "BEGIN:VCALENDAR" not in text:
                    raise ValueError("response is not an iCalendar document")
                self.cache_file.write_text(text)
                self.last_error = None
                return text
            except Exception as exc:  # noqa: BLE001 - stale data beats a blank panel
                self.last_error = f"{type(exc).__name__}: {exc}"
                if self.cache_file.exists():
                    return self.cache_file.read_text()
                return None

    # --- querying ----------------------------------------------------------

    def _to_local(self, value: datetime | date, end_of_day: bool = False) -> tuple[datetime, bool]:
        """Normalize an icalendar value to an aware local datetime.

        Returns (datetime, all_day). All-day entries arrive as plain dates and
        are anchored to local midnight so they sort alongside timed events.
        """
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=self.tz), False
            return value.astimezone(self.tz), False
        anchor = dtime(23, 59, 59) if end_of_day else dtime(0, 0)
        return datetime.combine(value, anchor, tzinfo=self.tz), True

    def events(self, now: datetime, lookahead_days: int = 14,
               include_hidden: bool = False) -> list[Event]:
        text = self.raw_ics()
        if not text:
            return []
        try:
            cal = icalendar.Calendar.from_ical(text)
            window_end = now + timedelta(days=lookahead_days)
            occurrences = recurring_ical_events.of(cal, skip_bad_series=True).between(
                now - timedelta(days=1), window_end
            )
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"parse failed: {type(exc).__name__}: {exc}"
            return []

        out: list[Event] = []
        for occ in occurrences:
            raw_start = occ.get("DTSTART")
            if raw_start is None:
                continue
            start, all_day = self._to_local(raw_start.dt)
            raw_end = occ.get("DTEND")
            if raw_end is not None:
                # For a DATE value, DTEND is EXCLUSIVE: a one-day all-day
                # event on the 19th is published as DTEND 20241120, meaning
                # "up to the start of the 20th". Anchoring that to the END of
                # the 20th gave every all-day entry an extra day of life -- it
                # stayed green as "happening now" through the following day,
                # and kept yesterday's column alive on the calendar panel.
                end, _ = self._to_local(raw_end.dt)
                if all_day and end <= start:
                    # Some exporters write DTEND equal to DTSTART for a single
                    # day, which is not legal and would otherwise make the
                    # event zero-length and invisible.
                    end = start + timedelta(days=1)
            else:
                end = start + timedelta(days=1) if all_day else start + timedelta(hours=1)
            raw = str(occ.get("SUMMARY", "(no title)")).strip()
            description = str(occ.get("DESCRIPTION", "") or "")
            clean, style = style_for(raw, description, self.mode_words)
            # `#hide` is how you keep something in the calendar but off the
            # panel. Mode detection still wants to see it: hiding the event
            # that arms a mode is a reasonable thing to want, and it would be
            # baffling if that also silently stopped the mode from firing.
            if style.hidden and not include_hidden:
                continue
            out.append(
                Event(
                    summary=clean or raw,
                    start=start,
                    end=end,
                    all_day=all_day,
                    location=str(occ.get("LOCATION", "") or "").strip(),
                    raw_summary=raw,
                    style=style,
                    calendar=self.name,
                )
            )
        for e in out:
            e.style = e.style.merged_over(self.default_style)
        return sorted(out, key=lambda e: e.start)

    def upcoming(self, now: datetime, lookahead_days: int = 14,
                 include_current: bool = True,
                 include_hidden: bool = False) -> list[Event]:
        """Events still relevant: in progress, or yet to start."""
        return [
            e for e in self.events(now, lookahead_days, include_hidden)
            if e.end > now and (include_current or e.start >= now)
        ]

    def today(self, now: datetime) -> list[Event]:
        end = datetime.combine(now.date(), dtime(23, 59, 59), tzinfo=self.tz)
        return [e for e in self.upcoming(now, lookahead_days=2) if e.start <= end]
