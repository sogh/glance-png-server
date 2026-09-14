"""Scores from ESPN's public site API -- any league it covers.

No key and no account. The one decision worth explaining is *which* endpoint:

    .../<sport>/<league>/scoreboard              3.8 MB for two weeks of NCAA
    .../<sport>/<league>/teams/<team>/schedule   200 KB for one team's season

The scoreboard returns every game in the country, which is a lot of bytes to
move so a panel can show one team's result. The per-team schedule carries that
team's whole season -- past results and future fixtures -- which is exactly
what "the last one and the next one" needs, and it takes the abbreviation
straight in the path, so `WASH` works without looking up a numeric id first.

One request per followed team. Follow four teams and that is four requests
every refresh, which is why the cache is per team and the interval is long.
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BASE = "https://site.api.espn.com/apis/site/v2/sports"

# Deliberately no User-Agent header: httpx's own is what gets through.
#
# ESPN's edge answers 403 to a browser-shaped UA ("Mozilla/5.0 ... Chrome")
# and to an unrecognised custom one ("glance-png-server"), but 200 to an
# honest client library ("python-httpx/0.27", "curl/8.7.1"). Tested three
# times each; it is consistent, not flaky. So do not "fix" this by adding a
# realistic browser User-Agent -- that is exactly what breaks it.

# ESPN uses 99 for "unranked", which is not a rank and must not be drawn as one.
UNRANKED = 99

STATE = {
    "STATUS_SCHEDULED": "pre",
    "STATUS_IN_PROGRESS": "live",
    "STATUS_HALFTIME": "live",
    "STATUS_END_PERIOD": "live",
    "STATUS_FINAL": "final",
    "STATUS_FULL_TIME": "final",
}

from .scores import FINAL, LIVE, OTHER, PRE, Fixture, Side  # noqa: E402


def _number(value: Any) -> int | None:
    """ESPN reports a score as a string, a number, or {value, displayValue}."""
    if isinstance(value, dict):
        value = value.get("value", value.get("displayValue"))
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _record(node: dict) -> str:
    for key in ("record", "records"):
        entries = node.get(key)
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if entry.get("name") in (None, "overall", "total"):
                    summary = entry.get("summary") or entry.get("displayValue")
                    if summary:
                        return str(summary)
    return ""


def _broadcast(comp: dict) -> str:
    for node in comp.get("broadcasts") or []:
        media = node.get("media") or {}
        name = media.get("shortName") or media.get("name")
        if name:
            return str(name)
        names = node.get("names")
        if isinstance(names, list) and names:
            return str(names[0])
        if node.get("market") and node.get("name"):
            return str(node["name"])
    return ""


def _logos(team: dict) -> tuple[str, ...]:
    """Candidate logo URLs, best first.

    ESPN's `500-dark` variant is drawn for dark backgrounds and is markedly
    better on an unlit panel -- Notre Dame's navy monogram becomes gold, Indiana's
    becomes white. Where no separate dark file exists the two are identical,
    so preferring it costs nothing.
    """
    out: list[str] = []
    for node in team.get("logos") or []:
        href = str(node.get("href") or "")
        if not href:
            continue
        rel = [str(r) for r in (node.get("rel") or [])]
        # Skip the 4096px brand-portal renders: they are huge and several are
        # drawn on a white or coloured plate, which composites to a bright
        # rectangle rather than a logo.
        if "primary_logo" in "".join(rel) or "secondary_logo" in "".join(rel):
            continue
        out.append(href)
        if "dark" in rel:
            out.insert(0, out.pop())
    single = str(team.get("logo") or "")
    if single and single not in out:
        out.append(single)
    return tuple(out)


def _side(node: dict) -> Side:
    team = node.get("team") or {}
    rank = (node.get("curatedRank") or {}).get("current")
    return Side(
        abbrev=str(team.get("abbreviation") or team.get("shortDisplayName") or "?"),
        name=str(team.get("shortDisplayName") or team.get("displayName")
                 or team.get("location") or ""),
        score=_number(node.get("score")),
        record=_record(node),
        rank=None if rank in (None, UNRANKED) else int(rank),
        winner=bool(node.get("winner", False)),
        logo=_logos(team),
        key=f"espn-{team.get('id') or team.get('abbreviation') or '?'}",
    )


class EspnSource:
    """One ESPN league. `league` is the "<sport>/<league>" path ESPN uses."""

    def __init__(self, league: str = "football/college-football", teams: str = "",
                 tz: ZoneInfo | None = None, cache_dir: Path | None = None,
                 refresh: int = 900, live_refresh: int = 60,
                 timeout: float = 12.0, name: str = "",
                 top: int = 0, poll: str = "ap", poll_refresh: int = 21600) -> None:
        self.league = str(league or "").strip("/ ")
        self.name = name or self.league
        self.fixed = [t.strip() for t in str(teams or "").split(",") if t.strip()]
        # Follow the top N of a poll as well as (or instead of) named teams.
        # The membership changes every week, which is the point -- "the top
        # four" is a standing instruction, not a list to keep editing.
        self.top = max(0, int(top or 0))
        self.poll = str(poll or "ap").lower()
        self.poll_refresh = poll_refresh
        self.tz = tz or ZoneInfo("UTC")
        self.refresh = refresh
        self.live_refresh = live_refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or ".")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.league and (self.fixed or self.top))

    @property
    def teams(self) -> list[str]:
        """Named teams first, then the current top N, without repeats.

        Named first so a team that is both -- Georgia sitting at #2 -- is
        fetched once and keeps its place, and so the list stays stable as the
        poll churns underneath it.
        """
        out = list(self.fixed)
        for abbrev in self.ranked():
            if abbrev not in out:
                out.append(abbrev)
        return out

    def ranked(self) -> list[str]:
        """The top `top` abbreviations of the configured poll.

        A failed fetch falls back to the cached poll, and then to nothing --
        the named teams still work, so a poll outage costs the extra teams
        rather than the whole panel.
        """
        if not self.top:
            return []
        path = self.rankings_file
        payload = None
        if path.exists():
            try:
                payload = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                payload = None
        stale = not path.exists() or time.time() - path.stat().st_mtime >= self.poll_refresh
        if stale:
            try:
                resp = httpx.get(f"{BASE}/{self.league}/rankings", timeout=self.timeout)
                resp.raise_for_status()
                fresh = resp.json()
                if isinstance(fresh, dict) and fresh.get("rankings"):
                    path.write_text(json.dumps(fresh))
                    payload = fresh
            except Exception as exc:  # noqa: BLE001 - stale poll beats no poll
                self.last_error = f"rankings: {type(exc).__name__}: {exc}"
        if not payload:
            return []

        polls = payload.get("rankings") or []
        chosen = next((p for p in polls if str(p.get("type", "")).lower() == self.poll), None)
        if chosen is None:
            chosen = polls[0] if polls else None
        if chosen is None:
            return []

        out: list[str] = []
        for entry in sorted(chosen.get("ranks") or [],
                            key=lambda e: int(e.get("current") or 999)):
            abbrev = str((entry.get("team") or {}).get("abbreviation") or "").strip()
            if abbrev and abbrev not in out:
                out.append(abbrev)
            if len(out) >= self.top:
                break
        return out

    def _slug(self, suffix: str) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", f"{self.league}-{suffix}").strip("-").lower()

    def _cache_file(self, team: str) -> Path:
        return self.cache_dir / f"espn-{self._slug(team)}.json"

    @property
    def rankings_file(self) -> Path:
        return self.cache_dir / f"espn-rankings-{self._slug(self.poll)}.json"

    def _ttl(self, payload: dict) -> int:
        """Poll hard only while something is actually being played."""
        for event in payload.get("events", []):
            for comp in event.get("competitions", []):
                if STATE.get(str((comp.get("status") or {}).get("type", {}).get("name"))) == LIVE:
                    return self.live_refresh
        return self.refresh

    def _payload(self, team: str) -> dict | None:
        path = self._cache_file(team)
        with self._lock:
            cached = None
            if path.exists():
                try:
                    cached = json.loads(path.read_text())
                except (json.JSONDecodeError, OSError):
                    cached = None
            if cached is not None and time.time() - path.stat().st_mtime < self._ttl(cached):
                return cached
            try:
                resp = httpx.get(f"{BASE}/{self.league}/teams/{team}/schedule",
                                 timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, dict) or "events" not in data:
                    raise ValueError("no events in response")
                path.write_text(json.dumps(data))
                self.last_error = None
                return data
            except Exception as exc:  # noqa: BLE001 - stale beats blank
                self.last_error = f"{team}: {type(exc).__name__}: {exc}"
                return cached

    def _fixture(self, event: dict) -> Fixture | None:
        comps = event.get("competitions") or []
        if not comps:
            return None
        comp = comps[0]
        sides = comp.get("competitors") or []
        if len(sides) < 2:
            return None
        home = next((s for s in sides if s.get("homeAway") == "home"), sides[0])
        away = next((s for s in sides if s.get("homeAway") == "away"), sides[-1])

        status = (comp.get("status") or event.get("status") or {}).get("type", {}) or {}
        state = STATE.get(str(status.get("name")), OTHER)
        if state is OTHER and status.get("completed"):
            state = FINAL

        start = None
        raw = event.get("date") or comp.get("date")
        if raw:
            try:
                start = datetime.fromisoformat(
                    str(raw).replace("Z", "+00:00")).astimezone(self.tz)
            except ValueError:
                start = None

        detail = str(status.get("shortDetail") or status.get("detail") or "")
        if state == PRE:
            # For a game not yet played the "detail" is just the start time,
            # which the panel already draws from `start`.
            detail = ""
        return Fixture(
            away=_side(away), home=_side(home), state=state, start=start,
            detail=detail, broadcast=_broadcast(comp), league=self.name,
            note=str((event.get("seasonType") or {}).get("name", "") or ""),
        )

    def fixtures(self, now: datetime) -> list[Fixture]:
        if not self.configured:
            self.last_error = "no teams configured"
            return []
        out: list[Fixture] = []
        seen: set[tuple] = set()
        for team in self.teams:
            payload = self._payload(team)
            if not payload:
                continue
            for event in payload.get("events", []):
                fixture = self._fixture(event)
                if fixture is None:
                    continue
                # Two followed teams playing each other would otherwise appear
                # twice, and the rotation would show the same game back to back.
                key = (fixture.away.abbrev, fixture.home.abbrev,
                       fixture.start.isoformat() if fixture.start else "")
                if key in seen:
                    continue
                seen.add(key)
                out.append(fixture)
        return sorted(out, key=lambda f: f.start or now)
