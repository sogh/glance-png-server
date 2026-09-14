"""Modes: a calendar event that changes what the panels show, while it runs.

The alternative was a button. A button has to be pressed twice -- once to turn
the thing on and once to remember, later, to turn it off -- and the second
press is the one that gets forgotten, so the panel ends up stuck on a welcome
banner for a fortnight. An event has an end time. It cleans up after itself,
it can be scheduled a week ahead from a phone, and the thing you already do
to plan a visit is the thing that arms it.

A mode is on whenever a matching event is in progress:

    modes:
      visitors:
        match: ["#visitors", "open house"]

Then any channel entry can ask for it:

    when: { mode: visitors }        only while the mode is on
    when: { not_mode: visitors }    only while it is off

Matching runs against the title exactly as typed. A `#tag` matches a tag; a
bare phrase matches case-insensitively on word boundaries, so "open house"
fires on "Open House 2pm" but not on "reopen household budget".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

# How far either side of now to bother parsing. Modes are a "right now"
# question, so a day each way is plenty and keeps the parse small.
LOOKAHEAD_DAYS = 2


def _pattern(term: str) -> re.Pattern[str] | None:
    """A word-bounded, case-insensitive matcher for one search term."""
    term = str(term or "").strip()
    if not term:
        return None
    if term.startswith("#"):
        word = term[1:]
        if not word:
            return None
        return re.compile(rf"(?:^|\s)#{re.escape(word)}\b", re.I)
    # \b does not work against a term that starts or ends in punctuation, so
    # only ask for a boundary where the term actually has a word character.
    lead = r"\b" if term[:1].isalnum() else ""
    trail = r"\b" if term[-1:].isalnum() else ""
    return re.compile(lead + re.escape(term) + trail, re.I)


@dataclass
class Mode:
    """One named mode and what turns it on."""

    name: str
    match: list[str] = field(default_factory=list)
    calendars: str | None = None          # None = look in all of them

    def __post_init__(self) -> None:
        # A mode with no `match` is triggered by its own name as a tag, which
        # is what almost everyone wants and saves a line of config.
        if not self.match:
            self.match = [f"#{self.name}"]
        self._patterns = [p for p in (_pattern(t) for t in self.match) if p]

    @property
    def tags(self) -> set[str]:
        """The `#words` this mode answers to, lowercased and without the hash.

        The calendar strips these from titles before drawing them, so an event
        called "Farm tour #visitors" shows up as "Farm tour".
        """
        return {t[1:].lower() for t in self.match if t.startswith("#") and len(t) > 1}

    def matches(self, title: str) -> bool:
        return any(p.search(title or "") for p in self._patterns)


class ModeSet:
    """The configured modes, and which of them are on right now."""

    def __init__(self, specs: dict[str, Any] | None = None) -> None:
        self.modes: dict[str, Mode] = {}
        for name, spec in (specs or {}).items():
            spec = spec or {}
            if isinstance(spec, str):            # `visitors: "#visitors"`
                spec = {"match": [spec]}
            if isinstance(spec, list):           # `visitors: ["#visitors"]`
                spec = {"match": spec}
            if not spec.get("enabled", True):
                continue
            raw = spec.get("match") or spec.get("keywords") or []
            if isinstance(raw, str):
                raw = [raw]
            calendars = spec.get("calendars", spec.get("calendar"))
            self.modes[str(name)] = Mode(
                name=str(name),
                match=[str(t) for t in raw],
                calendars=str(calendars) if calendars else None,
            )

    def __bool__(self) -> bool:
        return bool(self.modes)

    @property
    def names(self) -> list[str]:
        return list(self.modes)

    @property
    def tag_words(self) -> frozenset[str]:
        """Every mode tag, for the calendar to strip out of titles."""
        out: set[str] = set()
        for mode in self.modes.values():
            out |= mode.tags
        return frozenset(out)

    def active(self, now: datetime, calendars: Any) -> frozenset[str]:
        """Which modes are on, judged by events in progress at `now`.

        A broken or unreachable calendar means no modes, never an exception --
        a feed that fails to parse must not take the panel down with it.
        """
        if not self.modes or calendars is None:
            return frozenset()
        on: set[str] = set()
        for mode in self.modes.values():
            try:
                events = calendars.upcoming(
                    now, names=mode.calendars,
                    lookahead_days=LOOKAHEAD_DAYS, include_current=True,
                    include_hidden=True,
                )
            except Exception:  # noqa: BLE001 - a bad feed must not stall the panel
                continue
            for event in events:
                if event.is_now(now) and mode.matches(event.raw_summary or event.summary):
                    on.add(mode.name)
                    break
        return frozenset(on)

    def describe(self, now: datetime, calendars: Any) -> dict[str, Any]:
        """What /api/status reports, so "why is my banner not up" is answerable."""
        live = self.active(now, calendars)
        return {
            name: {"active": name in live, "match": mode.match,
                   "calendars": mode.calendars or "all"}
            for name, mode in self.modes.items()
        }


def active_titles(modes: Iterable[str]) -> str:
    return ", ".join(sorted(modes))
