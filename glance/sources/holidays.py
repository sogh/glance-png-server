"""Holiday definitions and the date maths to resolve them for a given year.

Supports three ways to pin a holiday to a date:
  date: "12-25"                              fixed month-day
  rule: {nth: 4, weekday: thu, month: 11}    nth weekday of a month (-1 = last)
  rule: {easter_offset: -2}                  days relative to Easter Sunday
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def easter(year: int) -> date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    lam = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lam) // 451
    month, day = divmod(h + lam - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    """nth occurrence of a weekday in a month; nth=-1 means the last one."""
    if nth > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (nth - 1))
    last = date(year, month, calendar.monthrange(year, month)[1])
    offset = (last.weekday() - weekday) % 7
    return last - timedelta(days=offset)


@dataclass
class Holiday:
    name: str
    slug: str
    window: int = 0                  # days before the date it starts showing
    after: int = 0                   # days after it keeps showing
    color: str = "white"
    accent: str = "amber"
    subtitle: str | None = None
    image: str | None = None         # static PNG under assets/static
    countdown: bool = False          # show "IN 3 DAYS" during the lead-up
    spec: dict[str, Any] = field(default_factory=dict)

    def occurrence(self, year: int) -> date | None:
        if "date" in self.spec:
            raw = str(self.spec["date"])
            parts = [int(p) for p in raw.replace("/", "-").split("-")]
            if len(parts) == 2:
                return date(year, parts[0], parts[1])
            if len(parts) == 3:
                return date(parts[0], parts[1], parts[2])
            raise ValueError(f"{self.name}: bad date {raw!r}")

        rule = self.spec.get("rule") or {}
        if "easter_offset" in rule:
            return easter(year) + timedelta(days=int(rule["easter_offset"]))
        if "weekday" in rule:
            wd = rule["weekday"]
            weekday = WEEKDAYS[str(wd)[:3].lower()] if isinstance(wd, str) else int(wd)
            return nth_weekday(year, int(rule["month"]), weekday, int(rule.get("nth", 1)))
        return None

    def active_on(self, today: date) -> tuple[bool, int] | tuple[bool, None]:
        """Is this holiday showing today, and how many days until it lands?

        Checks the neighbouring years too so a New Year's window that opens in
        late December still resolves.
        """
        for year in (today.year - 1, today.year, today.year + 1):
            occ = self.occurrence(year)
            if occ is None:
                continue
            delta = (occ - today).days
            if -self.after <= delta <= self.window:
                return True, delta
        return False, None


def load_holidays(path: str | Path) -> list[Holiday]:
    p = Path(path)
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or []
    out: list[Holiday] = []
    for item in raw:
        name = str(item["name"])
        slug = str(item.get("slug") or name.lower().replace(" ", "-").replace("'", ""))
        out.append(
            Holiday(
                name=name,
                slug=slug,
                window=int(item.get("window", 0)),
                after=int(item.get("after", 0)),
                color=str(item.get("color", "white")),
                accent=str(item.get("accent", "amber")),
                subtitle=item.get("subtitle"),
                image=item.get("image"),
                countdown=bool(item.get("countdown", False)),
                spec=item,
            )
        )
    return out


def active_holidays(holidays: list[Holiday], today: date) -> list[tuple[Holiday, int]]:
    """Holidays showing today, soonest first (the day itself sorts first)."""
    hits = []
    for h in holidays:
        ok, delta = h.active_on(today)
        if ok and delta is not None:
            hits.append((h, delta))
    return sorted(hits, key=lambda hd: (abs(hd[1]), hd[1]))
