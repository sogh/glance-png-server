"""Scores from any configured scoreboard: NCAA football, the WPBL, whatever.

The sibling of `baseball`, which stays bespoke because MLB's own API carries
things nobody else does -- the half-inning, per-side broadcast feeds. This one
draws whatever a `sources/scores.py` Fixture holds, so a new league is a
config entry rather than a scene.
"""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register


def _board(ctx: RenderContext, params: dict[str, Any]):
    boards = getattr(ctx, "scoreboards", None) or {}
    wanted = str(params.get("board", "") or "").strip()
    if wanted:
        return boards.get(wanted)
    return next(iter(boards.values()), None)


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    board = _board(ctx, params)
    if board is None:
        return False
    snap = board.snapshot(ctx.now)
    return bool(snap and (snap["live"] or snap["next"] or snap["last"]))


def clock(fixture) -> str:
    """A start time short enough to sit beside a matchup."""
    if not fixture.start:
        return "TBD"
    hour = fixture.start.hour % 12 or 12
    suffix = "A" if fixture.start.hour < 12 else "P"
    minute = f":{fixture.start.minute:02d}" if fixture.start.minute else ""
    return f"{hour}{minute}{suffix}"


def day_of(fixture, now) -> str:
    """'' for today, 'SAT' for later this week, 'SEP 19' beyond that."""
    if not fixture.start:
        return ""
    days = (fixture.start.date() - now.date()).days
    if days <= 0:
        return ""
    if days == 1:
        return "TMRW"
    if days < 7:
        return fixture.start.strftime("%a").upper()
    return fixture.start.strftime("%b %-d").upper()


@register("scores", available=_available,
          description="Score and next fixture from a configured scoreboard",
          params=[
              Param("board", "select", None, options="@boards",
                    help="Which configured scoreboard to read"),
              Param("accent", "color", "amber", options="@colors"),
              Param("label", "bool", True, help="Show the league name"),
              Param("broadcast", "bool", True, help="Show where to watch"),
              Param("rank", "bool", True, help="Show poll rankings where there are any"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_scores(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small = get_font("3x5")
    accent = params.get("accent", "amber")

    board = _board(ctx, params)
    snap = board.snapshot(ctx.now) if board is not None else None
    if not snap:
        name = (board.label or board.name).upper() if board is not None else "SCORES"
        reason = (board.last_error if board is not None and board.last_error
                  else "no game found")
        c.centered(name[:24], dim(accent, 0.9), small, y=6)
        c.centered(str(reason)[:44], "dim", small, y=17, max_width=c.width - 4)
        return c

    show_tv = bool(params.get("broadcast", True))
    show_rank = bool(params.get("rank", True))
    tag = (board.label or board.name).upper() if bool(params.get("label", True)) else ""

    # How the next fixture is phrased depends on how many teams are followed.
    # "AT DUQ" is clear when there is one; with two it hides which of them is
    # playing, and with none there is no "us" at all.
    following = len(board.teams)

    if snap["live"]:
        return _live(c, snap["live"], accent, small, show_tv, tag, show_rank)

    y = 2
    if snap["last"]:
        _result(c, snap["last"], ctx.now, y, accent, small, tag, show_rank)
        y += 11
    if snap["next"]:
        _next(c, snap["next"], ctx.now, y, accent, small, show_tv, show_rank,
              tag if not snap["last"] else "", following)
    elif snap["last"] and show_tv and snap["last"].broadcast:
        c.text(2, y + 2, snap["last"].broadcast, dim("grey", 0.85), small,
               max_width=c.width - 4)
    return c


def _matchup(side, show_rank: bool) -> str:
    return f"{side.label(show_rank)} {'' if side.score is None else side.score}".strip()


def _live(c, fixture, accent, small, show_tv, tag, show_rank):
    """A game in progress earns the whole panel."""
    big = get_font("5x7")
    text = (f"{_matchup(fixture.away, show_rank)}  "
            f"{_matchup(fixture.home, show_rank)}")
    scale = 2 if big.measure(text) * 2 <= c.width - 6 else 1
    c.centered(text, "white", big, y=3, max_width=c.width - 4, scale=scale)

    left = fixture.detail or "LIVE"
    c.text(2, 23, left[:22], "green", small, max_width=96)
    right = fixture.broadcast if show_tv else ""
    if not right and tag:
        right = tag
    if right:
        c.text(c.width - 2, 23, right, dim("grey", 0.9), small, "right",
               max_width=c.width - 100)
    return c


def _result(c, fixture, now, y, accent, small, tag, show_rank):
    """One finished game: who played, the score, and whether we won.

    Drawn as separate runs rather than one string so the gaps can differ. A
    uniform space put "USU" hard against "14" and made the pair read as one
    token, and a rank in front of that turned "19 WASH 16" into two numbers
    with a team name wedged between them.
    """
    head = (tag or "FINAL")[:10]
    c.text(2, y, head, dim(accent, 0.8), small)
    x = 2 + small.measure(head) + 6

    right_edge = c.width - 2 - small.measure("W") - 4
    for side in (fixture.away, fixture.home):
        # Green for the winner, dimmed for the loser. With no winner recorded
        # -- a hand-entered feed that has the score but not the result yet --
        # both stay neutral rather than inventing one.
        colour = ("green" if side.winner
                  else dim("white", 0.5) if _has_winner(fixture)
                  else dim("white", 0.8))
        if show_rank and side.ranked:
            rank = str(side.rank)
            c.text(x, y - 1, rank, dim(accent, 0.75), small)
            x += small.measure(rank) + 3
        c.text(x, y - 1, side.abbrev, colour, small)
        x += small.measure(side.abbrev) + 4
        if side.score is not None:
            score = str(side.score)
            c.text(x, y - 1, score, colour, small)
            x += small.measure(score) + 8
        else:
            x += 4
        if x > right_edge:
            break

    won = fixture.won()
    if won is not None:
        c.text(c.width - 2, y, "W" if won else "L",
               "green" if won else dim("white", 0.55), small, "right")
    else:
        # No "us" in this game, so the slot says when it was instead -- more
        # use than a blank corner on a league-wide board.
        day = fixture.start.strftime("%b %-d").upper() if fixture.start else ""
        if day and 2 + small.measure(day) < c.width - x:
            c.text(c.width - 2, y, day, dim("grey", 0.7), small, "right")


def _has_winner(fixture) -> bool:
    return fixture.away.winner or fixture.home.winner


def _next(c, fixture, now, y, accent, small, show_tv, show_rank, tag, following):
    """The next fixture: when, against whom, and where to watch."""
    big = get_font("5x7")
    mine, opponent = fixture.mine(), fixture.opponent()
    when = " ".join(x for x in (day_of(fixture, now), clock(fixture)) if x)

    if opponent is None or following == 0:
        # Following the whole league: there is no "us", so name both sides.
        headline = f"{fixture.away.label(show_rank)} V {fixture.home.label(show_rank)}  {when}"
    else:
        # "AT"/"VS" rather than "@": the at-sign is a dense knot of pixels at
        # this size and reads as a smudge, where two letters are unambiguous.
        at = "AT" if fixture.side_for() == "away" else "VS"
        # With more than one team followed, "AT DUQ" does not say who is
        # playing -- the last result and the next fixture routinely belong to
        # different teams.
        who = f"{mine.abbrev} " if following > 1 and mine is not None else ""
        headline = f"{who}{at} {opponent.label(show_rank)}  {when}"

    label = tag or "NEXT"
    label_w = small.measure(label) + 5
    c.text(2, y + 2, label, dim(accent, 0.8), small)
    c.text(2 + label_w, y, headline, "white", big, "left",
           c.width - 4 - label_w, 1)

    if show_tv and fixture.broadcast:
        tv_y = y + big.height + 3
        if tv_y + small.height <= c.height:
            c.text(2, tv_y, fixture.broadcast, dim("grey", 0.85), small,
                   max_width=c.width - 4)
