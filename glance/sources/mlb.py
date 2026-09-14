"""MLB in the shared scoreboard vocabulary.

A thin adapter rather than a rewrite. `sources/baseball.py` already talks to
statsapi and knows two things nothing else does -- the current half-inning,
and which broadcast a fan of *your* team would actually turn on -- so it stays
as it is and this translates what it returns into `Fixture`s.

ESPN's own MLB endpoint would have been simpler and is not used: a team's
schedule there is 162 games and 2.8 MB, where statsapi answers a three-day
window in a few kilobytes. Its logos are worth having though, so those come
from ESPN's CDN, addressed by the lowercase abbreviation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .baseball import BaseballSource
from .scores import FINAL, LIVE, OTHER, PRE, Fixture, Side

LOGO = "https://a.espncdn.com/i/teamlogos/mlb/500{variant}/{slug}.png"

# statsapi and ESPN agree on 29 of the 30 abbreviations. Checked against every
# team; this is the only one that 404s.
LOGO_SLUG = {"AZ": "ari"}

STATE = {"Live": LIVE, "Final": FINAL, "Preview": PRE}


def logos_for(abbrev: str) -> tuple[str, ...]:
    slug = LOGO_SLUG.get(abbrev.upper(), abbrev.lower())
    if not slug:
        return ()
    return (LOGO.format(variant="-dark", slug=slug),
            LOGO.format(variant="", slug=slug))


def _side(side: Any) -> Side:
    record = f"{side.wins}-{side.losses}" if (side.wins or side.losses) else ""
    return Side(
        abbrev=side.abbrev,
        name=side.name,
        score=side.score,
        record=record,
        winner=bool(side.is_winner),
        logo=logos_for(side.abbrev),
        key=f"mlb-{side.abbrev.lower()}",
    )


class MlbSource:
    def __init__(self, teams: str = "", tz: ZoneInfo | None = None,
                 cache_dir: Path | None = None, refresh: int = 600,
                 live_refresh: int = 60, timeout: float = 12.0,
                 name: str = "MLB") -> None:
        self.name = name
        self.inner = BaseballSource(teams=teams, tz=tz, cache_dir=cache_dir,
                                    refresh=refresh, live_refresh=live_refresh,
                                    timeout=timeout)

    @property
    def teams(self) -> list[str]:
        return list(self.inner.teams)

    @property
    def configured(self) -> bool:
        return self.inner.configured

    @property
    def last_error(self) -> str | None:
        return self.inner.last_error

    @last_error.setter
    def last_error(self, value: str | None) -> None:
        self.inner.last_error = value

    def fixtures(self, now: datetime) -> list[Fixture]:
        if not self.configured:
            self.last_error = "no teams configured"
            return []
        out: list[Fixture] = []
        for game in self.inner._games(now):
            state = STATE.get(game.abstract, OTHER)
            # The broadcast is resolved here, against whichever followed team
            # is playing, because a Fixture carries one feed and the whole
            # point is that it is *ours*: a Mariners fan watching a road game
            # wants Mariners.TV, not the home network.
            mine = next((t for t in self.inner.teams if game.side_for(t)), "")
            detail = ""
            if state == LIVE and game.inning:
                detail = f"{game.inning_state[:3].upper()} {game.inning}".strip()
            out.append(Fixture(
                away=_side(game.away), home=_side(game.home), state=state,
                start=game.start, detail=detail,
                broadcast=game.broadcast_for(mine) if mine else "",
                league=self.name,
            ))
        return sorted(out, key=lambda f: f.start or now)
