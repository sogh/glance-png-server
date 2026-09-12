"""MLB scores from the league's own public Stats API.

statsapi.mlb.com needs no key and no account, and it carries everything a
panel wants: scores, the current inning, the final result, the local start
time, and the broadcast listings.

The broadcasts matter more than they look. Each game lists feeds for both
sides, so "where to watch" depends on which team *you* follow -- a Mariners
fan watching a road game wants Mariners.TV, not the home team's network. An
app that just prints the first broadcast in the list gets this wrong half the
time.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

BASE = "https://statsapi.mlb.com/api/v1"
LIVE_STATES = {"Live", "In Progress", "Manager Challenge", "Warmup", "Pre-Game"}


@dataclass
class Side:
    abbrev: str
    name: str
    score: int | None = None
    wins: int = 0
    losses: int = 0
    is_winner: bool = False


@dataclass
class Game:
    away: Side
    home: Side
    state: str                     # detailedState, as MLB words it
    abstract: str                  # Preview | Live | Final
    start: datetime | None = None
    inning: str = ""               # "7th"
    inning_state: str = ""         # "Top" | "Bottom" | "Middle" | "End"
    broadcasts: list[dict] = field(default_factory=list)

    @property
    def live(self) -> bool:
        return self.abstract == "Live"

    @property
    def final(self) -> bool:
        return self.abstract == "Final"

    @property
    def started(self) -> bool:
        """Whether a score means anything yet.

        MLB reports 0-0 for a game in Pre-Game state, and drawing that as a
        score makes a game that has not begun look like a scoreless one in
        progress -- which is precisely the sort of confident wrongness worth
        avoiding.
        """
        return self.abstract in ("Live", "Final")

    def side_for(self, abbrev: str) -> str:
        """'home', 'away', or '' if this team is not playing."""
        if self.home.abbrev == abbrev:
            return "home"
        if self.away.abbrev == abbrev:
            return "away"
        return ""

    def broadcast_for(self, abbrev: str) -> str:
        """The TV feed a fan of `abbrev` would actually turn on.

        Falls back to any TV listing, then radio, so a game is never left
        looking unwatchable just because the home feed is missing.
        """
        side = self.side_for(abbrev)
        tv = [b for b in self.broadcasts if b.get("type") == "TV"]
        if side:
            mine = [b for b in tv if b.get("homeAway") == side]
            if mine:
                return str(mine[0].get("name") or mine[0].get("callSign") or "")
        if tv:
            return str(tv[0].get("name") or tv[0].get("callSign") or "")
        radio = [b for b in self.broadcasts if b.get("type") in ("AM", "FM")]
        if radio:
            return str(radio[0].get("name") or radio[0].get("callSign") or "")
        return ""


def _side(node: dict) -> Side:
    team = node.get("team", {})
    record = node.get("leagueRecord", {}) or {}
    return Side(
        abbrev=str(team.get("abbreviation") or "?"),
        name=str(team.get("teamName") or team.get("name") or ""),
        score=node.get("score"),
        wins=int(record.get("wins", 0) or 0),
        losses=int(record.get("losses", 0) or 0),
        is_winner=bool(node.get("isWinner", False)),
    )


class BaseballSource:
    def __init__(self, teams: str = "", tz: ZoneInfo | None = None,
                 cache_dir: Path | None = None, refresh: int = 600,
                 live_refresh: int = 60, timeout: float = 12.0) -> None:
        self.teams = [t.strip().upper() for t in str(teams or "").split(",") if t.strip()]
        self.tz = tz or ZoneInfo("UTC")
        self.refresh = refresh
        self.live_refresh = live_refresh
        self.timeout = timeout
        self.cache_dir = Path(cache_dir or ".")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "baseball.json"
        self.last_error: str | None = None
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.teams)

    def _ttl(self, payload: dict) -> int:
        """Poll harder while a game is actually being played."""
        for date in payload.get("dates", []):
            for game in date.get("games", []):
                if game.get("status", {}).get("abstractGameState") == "Live":
                    return self.live_refresh
        return self.refresh

    def _payload(self, now: datetime) -> dict | None:
        with self._lock:
            cached = None
            if self.cache_file.exists():
                try:
                    cached = json.loads(self.cache_file.read_text())
                except (json.JSONDecodeError, OSError):
                    cached = None
            if cached is not None:
                age = time.time() - self.cache_file.stat().st_mtime
                if age < self._ttl(cached):
                    return cached
            try:
                # Yesterday through tomorrow: enough to find a game in progress,
                # one coming up, or the last one that finished.
                start = (now - timedelta(days=1)).date().isoformat()
                end = (now + timedelta(days=1)).date().isoformat()
                resp = httpx.get(f"{BASE}/schedule", timeout=self.timeout, params={
                    "sportId": 1, "startDate": start, "endDate": end,
                    "hydrate": "team,linescore,broadcasts(all)",
                })
                resp.raise_for_status()
                data = resp.json()
                self.cache_file.write_text(json.dumps(data))
                self.last_error = None
                return data
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{type(exc).__name__}: {exc}"
                return cached

    def _games(self, now: datetime) -> list[Game]:
        payload = self._payload(now)
        if not payload:
            return []
        out: list[Game] = []
        for date in payload.get("dates", []):
            for node in date.get("games", []):
                status = node.get("status", {})
                line = node.get("linescore", {}) or {}
                start = None
                raw = node.get("gameDate")
                if raw:
                    try:
                        start = datetime.fromisoformat(
                            raw.replace("Z", "+00:00")).astimezone(self.tz)
                    except ValueError:
                        start = None
                out.append(Game(
                    away=_side(node["teams"]["away"]),
                    home=_side(node["teams"]["home"]),
                    state=str(status.get("detailedState") or ""),
                    abstract=str(status.get("abstractGameState") or ""),
                    start=start,
                    inning=str(line.get("currentInningOrdinal") or ""),
                    inning_state=str(line.get("inningState") or ""),
                    broadcasts=node.get("broadcasts") or [],
                ))
        return out

    def snapshot(self, now: datetime) -> dict | None:
        """Everything worth knowing at once: what is on now, what just
        happened, and what is next.

        A result stays interesting for a while after the final out, and then
        the next fixture becomes the thing you want. Returning all three lets
        the panel show both rather than choosing.
        """
        if not self.configured:
            self.last_error = "no teams configured"
            return None

        mine = [(g, t) for g in self._games(now) for t in self.teams if g.side_for(t)]
        if not mine:
            return None

        live = [p for p in mine if p[0].live]
        upcoming = [p for p in mine if p[0].abstract == "Preview"
                    and p[0].start and p[0].start >= now]
        done = [p for p in mine if p[0].final and p[0].start]

        return {
            "team": mine[0][1],
            "live": min(live, key=lambda p: p[0].start or now)[0] if live else None,
            "next": min(upcoming, key=lambda p: p[0].start)[0] if upcoming else None,
            "last": max(done, key=lambda p: p[0].start)[0] if done else None,
        }

    def game(self, now: datetime) -> tuple[Game, str] | None:
        """The game worth showing, and which followed team it belongs to.

        Priority: one being played now, then the next one coming up, then the
        last one that finished. That ordering is the whole point -- a panel
        should show the live game if there is one, and only fall back to
        yesterday's result when there is nothing else.
        """
        if not self.configured:
            self.last_error = "no teams configured"
            return None

        mine = [(g, t) for g in self._games(now) for t in self.teams if g.side_for(t)]
        if not mine:
            return None

        live = [p for p in mine if p[0].live]
        if live:
            return min(live, key=lambda p: p[0].start or now)

        upcoming = [p for p in mine if p[0].abstract == "Preview"
                    and p[0].start and p[0].start >= now]
        if upcoming:
            return min(upcoming, key=lambda p: p[0].start)

        done = [p for p in mine if p[0].final and p[0].start]
        if done:
            return max(done, key=lambda p: p[0].start)
        # Nothing live, upcoming or finished: fall back to whichever is
        # nearest in time rather than whichever happened to parse first.
        dated = [p for p in mine if p[0].start]
        if dated:
            return min(dated, key=lambda p: abs((p[0].start - now).total_seconds()))
        return mine[0]
