"""One vocabulary for scores, whatever league they came from.

Every provider speaks its own dialect -- MLB says `abstractGameState`, ESPN
says `STATUS_FINAL`, the WPBL's WordPress says `final` -- and none of that is
the panel's business. Each source translates into the `Fixture` below, and a
single scene draws all of them.

`pick` is the part worth reading twice. A panel should show the game being
played right now; failing that the next one; failing that the last result,
which stays interesting for a day or so after the final out. Getting that
order wrong is how a scoreboard ends up showing Saturday's win while Sunday's
game is in the sixth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Protocol

# What a source may report. Anything it cannot map becomes "other", which the
# panel treats as "no useful state" rather than guessing.
PRE, LIVE, FINAL, OTHER = "pre", "live", "final", "other"


@dataclass
class Side:
    abbrev: str
    name: str = ""
    score: int | None = None
    record: str = ""                  # "3-1"
    rank: int | None = None           # AP/coaches poll, where a league has one
    winner: bool = False
    logo: tuple[str, ...] = ()        # candidate URLs, best first
    key: str = ""                     # stable cache key for the logo

    @property
    def ranked(self) -> bool:
        return self.rank is not None and 1 <= self.rank <= 25

    def label(self, with_rank: bool = False) -> str:
        if with_rank and self.ranked:
            return f"{self.rank} {self.abbrev}"
        return self.abbrev


@dataclass
class Fixture:
    away: Side
    home: Side
    state: str = OTHER
    start: datetime | None = None
    detail: str = ""                  # "7th", "Q3 4:12", "Final/OT"
    broadcast: str = ""
    league: str = ""
    note: str = ""                    # "CHAMPIONSHIP G3", say
    following: str = ""               # which configured team this was matched for

    def _team(self, team: str | None) -> str:
        return team if team is not None else self.following

    @property
    def live(self) -> bool:
        return self.state == LIVE

    @property
    def final(self) -> bool:
        return self.state == FINAL

    @property
    def started(self) -> bool:
        """Whether a score means anything yet.

        Providers cheerfully report 0-0 for a game that has not begun, and
        drawing that makes it look like a scoreless game in progress -- the
        sort of confident wrongness worth going out of the way to avoid.
        """
        return self.state in (LIVE, FINAL)

    def side_for(self, team: str | None = None) -> str:
        """'home', 'away', or '' if this team is not in this fixture."""
        wanted = self._team(team).strip().lower()
        if not wanted:
            return ""
        for where, side in (("home", self.home), ("away", self.away)):
            if wanted in (side.abbrev.lower(), side.name.lower()):
                return where
        return ""

    def mine(self, team: str | None = None) -> Side | None:
        where = self.side_for(team)
        return self.home if where == "home" else self.away if where == "away" else None

    def opponent(self, team: str | None = None) -> Side | None:
        where = self.side_for(team)
        return self.away if where == "home" else self.home if where == "away" else None

    def won(self, team: str | None = None) -> bool | None:
        """True, False, or None when it is not yet a question worth asking."""
        if not self.final:
            return None
        side = self.mine(team)
        if side is None:
            return None
        if side.winner:
            return True
        other = self.opponent(team)
        if other is not None and other.winner:
            return False
        if side.score is None or other is None or other.score is None:
            return None
        return side.score > other.score


class ScoreSource(Protocol):
    """What the scene needs from any provider."""

    name: str
    last_error: str | None

    @property
    def configured(self) -> bool: ...

    def fixtures(self, now: datetime) -> list[Fixture]: ...


def matches_any(fixture: Fixture, teams: Iterable[str]) -> str:
    """The first configured team playing in this fixture, or ''."""
    for team in teams:
        if fixture.side_for(team):
            return team
    return ""


def pick(fixtures: list[Fixture], teams: list[str], now: datetime) -> dict[str, Any] | None:
    """What is on now, what just happened, and what is next.

    All three are returned rather than one, because a result stays worth
    knowing for a while after the whistle and the next fixture becomes
    interesting before the old result stops being so. Letting the scene have
    both means it can show both when they fit.
    """
    if not fixtures:
        return None

    if teams:
        owned = [(f, t) for f in fixtures if (t := matches_any(f, teams))]
    else:
        # No teams configured: follow the whole league. Sensible for a
        # four-team league, silly for a hundred-team one, and the config is
        # where that judgement belongs.
        owned = [(f, "") for f in fixtures]
    if not owned:
        return None

    # Which team each fixture was matched for travels WITH the fixture. Follow
    # two teams and the last result and the next fixture routinely belong to
    # different ones -- a single "team" on the snapshot would then be wrong
    # for at least one of them, and `won()` would answer None for a game that
    # was plainly won.
    for fixture, team in owned:
        fixture.following = team

    live = [p for p in owned if p[0].live]
    upcoming = [p for p in owned if p[0].state == PRE and p[0].start and p[0].start >= now]
    done = [p for p in owned if p[0].final and p[0].start]

    chosen = (min(live, key=lambda p: p[0].start or now) if live
              else min(upcoming, key=lambda p: p[0].start) if upcoming
              else max(done, key=lambda p: p[0].start) if done else owned[0])

    return {
        "team": chosen[1],
        "fixture": chosen[0],
        "live": min(live, key=lambda p: p[0].start or now)[0] if live else None,
        "next": min(upcoming, key=lambda p: p[0].start)[0] if upcoming else None,
        "last": max(done, key=lambda p: p[0].start)[0] if done else None,
    }


@dataclass
class Board:
    """A named scoreboard: one provider, one league, the teams you follow."""

    name: str
    source: Any
    label: str = ""

    @property
    def teams(self) -> list[str]:
        """Asked of the source every time, never cached here.

        A poll-driven board's membership changes weekly; a copy taken at
        startup would quietly follow last month's top four.
        """
        return list(getattr(self.source, "teams", []) or [])

    @property
    def configured(self) -> bool:
        return bool(self.source is not None and self.source.configured)

    @property
    def last_error(self) -> str | None:
        return getattr(self.source, "last_error", None)

    def snapshot(self, now: datetime) -> dict[str, Any] | None:
        if self.source is None:
            return None
        try:
            found = self.source.fixtures(now)
        except Exception as exc:  # noqa: BLE001 - a bad feed must not stall the panel
            self.source.last_error = f"{type(exc).__name__}: {exc}"
            return None
        return pick(found, self.teams, now)
