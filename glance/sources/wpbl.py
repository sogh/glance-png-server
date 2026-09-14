"""Women's Pro Baseball League scores.

The WPBL played its first season in 2026 -- four teams, a neutral park in
Springfield, Illinois. It is new enough that nobody carries it: ESPN's API has
twelve baseball leagues and this is not one of them, and there is no stats
vendor behind it.

What there is, is a WordPress site whose games are a custom post type with the
REST API left on:

    /wp-json/wp/v2/wpbl_game     game_date, teams, scores, status, broadcast
    /wp-json/wp/v2/wpbl_team     the four clubs, with abbreviations

That is a real feed rather than a scrape -- structured fields, not parsed
markup -- but it is worth knowing what it is. Scores are entered by hand by
whoever runs the site, so they arrive when someone types them, not at the
final out, and a field can be blank because nobody has filled it in yet. The
panel treats a missing score as "not known" rather than as nil.

The plugin returns every ACF field wrapped in its own definition, so asking
for forty games costs about a megabyte and asking for the nine fields we want
still costs 280 KB. Hence one request for the whole season, cached hard.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import date as date_cls, datetime, time as time_cls, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .scores import FINAL, LIVE, OTHER, PRE, Fixture, Side

BASE = "https://www.womensprobaseballleague.com/wp-json/wp/v2"
USER_AGENT = "glance-png-server"

GAME_FIELDS = ",".join((
    "id", "acf.game_date", "acf.game_time", "acf.game_timezone", "acf.game_status",
    "acf.away_team", "acf.home_team", "acf.away_score", "acf.home_score",
    "acf.game_broadcast_tv", "acf.game_broadcast_stream",
))
TEAM_FIELDS = "id,title,slug,acf.team_abbreviation,acf.team_logo"

STATE = {
    "scheduled": PRE,
    "in_progress": LIVE,
    "final": FINAL,
    "postponed": OTHER,
    "cancelled": OTHER,
}
# Teams change far less often than scores, so they get their own long life.
TEAM_TTL = 86400


def _stamp(fields: str) -> str:
    """A short fingerprint of a request, for the cache file name."""
    return hashlib.sha256(fields.encode()).hexdigest()[:8]


def acf(node: dict, key: str) -> Any:
    """Pull a value out of ACF's wrapper.

    Every field arrives as {value, value_formatted, field: {...the whole field
    definition...}}, so the value has to be dug out; a plain `.get(key)` gets
    the wrapper and quietly compares false against everything.
    """
    value = (node.get("acf") or {}).get(key)
    if isinstance(value, dict):
        for candidate in ("value", "value_formatted"):
            got = value.get(candidate)
            if got not in (None, ""):
                return got
        return None
    return value


def _int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class WpblSource:
    def __init__(self, teams: str = "", tz: ZoneInfo | None = None,
                 cache_dir: Path | None = None, refresh: int = 600,
                 live_refresh: int = 120, timeout: float = 15.0,
                 name: str = "WPBL") -> None:
        self.name = name
        self.teams = [t.strip() for t in str(teams or "").split(",") if t.strip()]
        self.tz = tz or ZoneInfo("UTC")
        self.refresh = refresh
        self.live_refresh = live_refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or ".")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # The requested field list is baked into the cache file name. Asking
        # for a new field otherwise reads a cached payload that predates it
        # and finds it missing -- and with a day-long TTL the new field simply
        # does not arrive until tomorrow. That cost a round of "why are there
        # no logos on the server"; the name now changes when the question does.
        self.games_file = self.cache_dir / f"wpbl-games-{_stamp(GAME_FIELDS)}.json"
        self.teams_file = self.cache_dir / f"wpbl-teams-{_stamp(TEAM_FIELDS)}.json"
        self.media_file = self.cache_dir / f"wpbl-media-{_stamp(TEAM_FIELDS)}.json"
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        # Four teams in the whole league, so following all of them is a
        # perfectly sensible default and an empty `teams` is not a misconfig.
        return True

    def _fetch(self, path: Path, url: str, params: dict, ttl: float) -> Any:
        cached = None
        if path.exists():
            try:
                cached = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                cached = None
        if cached is not None and time.time() - path.stat().st_mtime < ttl:
            return cached
        try:
            resp = httpx.get(url, params=params, timeout=self.timeout,
                             headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError("expected a list of posts")
            path.write_text(json.dumps(data))
            self.last_error = None
            return data
        except Exception as exc:  # noqa: BLE001 - stale beats blank
            self.last_error = f"{type(exc).__name__}: {exc}"
            return cached

    def _media(self, ids: list[int]) -> dict[int, str]:
        """Attachment id -> file url.

        The teams carry their logo as a media id rather than a url, so it
        takes a second call. One call for all four, cached as long as the
        teams themselves.
        """
        if not ids:
            return {}
        raw = self._fetch(self.media_file, f"{BASE}/media",
                          {"include": ",".join(str(i) for i in sorted(ids)),
                           "per_page": 50, "_fields": "id,source_url"},
                          TEAM_TTL) or []
        return {int(n.get("id", 0)): str(n.get("source_url") or "")
                for n in raw if n.get("source_url")}

    def _teams(self) -> dict[int, Side]:
        raw = self._fetch(self.teams_file, f"{BASE}/wpbl_team",
                          {"per_page": 50, "_fields": TEAM_FIELDS}, TEAM_TTL) or []
        wanted = [i for i in (_int(acf(n, "team_logo")) for n in raw) if i]
        media = self._media(wanted)
        out: dict[int, Side] = {}
        for node in raw:
            title = (node.get("title") or {}).get("rendered") or node.get("slug") or ""
            abbrev = acf(node, "team_abbreviation") or str(title)[:3].upper()
            team_id = int(node.get("id", 0))
            url = media.get(_int(acf(node, "team_logo")) or -1, "")
            out[team_id] = Side(abbrev=str(abbrev), name=str(title),
                                logo=(url,) if url else (),
                                key=f"wpbl-{team_id}")
        return out

    def _ttl(self, payload: Any) -> float:
        if isinstance(payload, list):
            for node in payload:
                if STATE.get(str(acf(node, "game_status") or "").lower()) == LIVE:
                    return self.live_refresh
        return self.refresh

    def _games(self) -> list[dict]:
        ttl = self.refresh
        if self.games_file.exists():
            try:
                ttl = self._ttl(json.loads(self.games_file.read_text()))
            except (json.JSONDecodeError, OSError):
                pass
        return self._fetch(self.games_file, f"{BASE}/wpbl_game",
                           {"per_page": 100, "_fields": GAME_FIELDS}, ttl) or []

    def _start(self, node: dict) -> datetime | None:
        raw = str(acf(node, "game_date") or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) != 8:
            return None
        try:
            day = date_cls(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
        except ValueError:
            return None

        clock = str(acf(node, "game_time") or "").strip()
        parts = [p for p in clock.split(":") if p.isdigit()]
        at = time_cls(int(parts[0]), int(parts[1])) if len(parts) >= 2 else time_cls(0, 0)

        zone = str(acf(node, "game_timezone") or "").strip()
        try:
            local = ZoneInfo(zone) if zone else self.tz
        except Exception:  # noqa: BLE001 - a typo in the feed is not fatal
            local = self.tz
        # Games are published in the park's own timezone, so they are read
        # there and then moved to ours -- not reinterpreted as local time,
        # which would shift a 6:30pm first pitch by two hours.
        return datetime.combine(day, at, tzinfo=local).astimezone(self.tz)

    def fixtures(self, now: datetime) -> list[Fixture]:
        teams = self._teams()
        out: list[Fixture] = []
        for node in self._games():
            home_id, away_id = _int(acf(node, "home_team")), _int(acf(node, "away_team"))
            if home_id is None or away_id is None:
                continue          # a placeholder like "Championship Game 5, if needed"
            home = teams.get(home_id) or Side(abbrev="?")
            away = teams.get(away_id) or Side(abbrev="?")
            state = STATE.get(str(acf(node, "game_status") or "").lower(), OTHER)
            home_score, away_score = _int(acf(node, "home_score")), _int(acf(node, "away_score"))

            home = Side(home.abbrev, home.name, home_score,
                        logo=home.logo, key=home.key)
            away = Side(away.abbrev, away.name, away_score,
                        logo=away.logo, key=away.key)
            if state == FINAL and home_score is not None and away_score is not None:
                home.winner, away.winner = home_score > away_score, away_score > home_score

            out.append(Fixture(
                away=away, home=home, state=state, start=self._start(node),
                broadcast=str(acf(node, "game_broadcast_tv")
                              or acf(node, "game_broadcast_stream") or ""),
                league=self.name,
            ))
        return sorted(out, key=lambda f: f.start or now)
