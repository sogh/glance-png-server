"""The score, and where to watch."""

from __future__ import annotations

from typing import Any

from ..canvas import Canvas
from ..fonts import get_font
from ..palette import dim
from .base import Param, RenderContext, register


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    if params.get("always"):
        return True
    source = ctx.baseball
    return source is not None and source.game(ctx.now) is not None


def start_text(game, tz) -> str:
    if not game.start:
        return "TBD"
    hour = game.start.hour % 12 or 12
    suffix = "A" if game.start.hour < 12 else "P"
    minute = f":{game.start.minute:02d}" if game.start.minute else ""
    return f"{hour}{minute}{suffix}"


@register("baseball", available=_available,
          description="Last result and next game for the teams you follow",
          params=[
              Param("accent", "color", "sky", options="@colors",
                    help="Highlight for the team you follow"),
              Param("broadcast", "bool", True, help="Show where to watch"),
              Param("record", "bool", True, help="Show the W-L record"),
              Param("background", "color", "black", options="@colors"),
          ])
def render_baseball(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    small, big = get_font("3x5"), get_font("5x7")
    accent = params.get("accent", "sky")

    source = ctx.baseball
    snap = source.snapshot(ctx.now) if source else None
    if not snap:
        reason = (source.last_error if source and source.last_error
                  else "no game found")
        c.centered("BASEBALL", dim(accent, 0.9), small, y=6)
        c.centered(str(reason)[:44], "dim", small, y=17, max_width=c.width - 4)
        return c

    team = snap["team"]
    show_tv = bool(params.get("broadcast", True))

    # A game in progress is the only thing worth the whole panel.
    if snap["live"]:
        return _live(c, snap["live"], team, accent, small, big, show_tv)

    # Otherwise the result still worth knowing, and the next fixture under it.
    y = 2
    if snap["last"]:
        _scoreline(c, snap["last"], team, y, accent, big, small)
        y += 11
    if snap["next"]:
        _upcoming(c, snap["next"], team, y, accent, big, small, show_tv,
                  labelled=bool(snap["last"]))
    elif snap["last"] and show_tv:
        tv = snap["last"].broadcast_for(team)
        if tv:
            c.text(2, y + 2, tv, dim("grey", 0.85), small, max_width=c.width - 4)
    return c


def _side_of(game, team):
    return game.away if game.side_for(team) == "away" else game.home


def _live(c, game, team, accent, small, big, show_tv):
    """Score large, inning and broadcast beneath."""
    text = f"{game.away.abbrev} {game.away.score}  {game.home.abbrev} {game.home.score}"
    scale = 2 if big.measure(text) * 2 <= c.width - 6 else 1
    c.centered(text, "white", big, y=3, max_width=c.width - 4, scale=scale)

    state = f"{game.inning_state[:3].upper()} {game.inning}".strip()
    c.text(2, 23, state, "green", small, max_width=80)
    if show_tv:
        tv = game.broadcast_for(team)
        if tv:
            c.text(c.width - 2, 23, tv, dim("grey", 0.9), small, "right",
                   max_width=c.width - 90)
    return c


def _scoreline(c, game, team, y, accent, big, small):
    """One finished game: abbreviations, scores, and who won."""
    mine = _side_of(game, team)
    won = mine.is_winner
    c.text(2, y, "FINAL", dim(accent, 0.8), small)

    x = 2 + small.measure("FINAL") + 5
    for owner in (game.away, game.home):
        colour = "green" if owner.is_winner else dim("white", 0.5)
        c.text(x, y - 1, owner.abbrev, colour, small)
        x += small.measure(owner.abbrev) + 2
        c.text(x, y - 1, str(owner.score), colour, small)
        x += small.measure(str(owner.score)) + 6

    c.text(c.width - 2, y, "W" if won else "L",
           "green" if won else dim("white", 0.55), small, "right")


def _upcoming(c, game, team, y, accent, big, small, show_tv, labelled):
    """The next fixture: when, against whom, and where to watch."""
    opponent = game.home if game.side_for(team) == "away" else game.away
    # "AT" rather than "@": the at-sign is a dense little knot of pixels at
    # 5x7 and reads as a smudge, where two letters are unambiguous.
    at = "AT" if game.side_for(team) == "away" else "VS"
    when = _when(game, team)

    headline = f"{at} {opponent.abbrev}  {when}"
    label_w = small.measure("NEXT") + 5
    room = c.width - 4 - label_w
    scale = 2 if (not labelled and big.measure(headline) * 2 <= room) else 1

    c.text(2, y + 2, "NEXT", dim(accent, 0.8), small)
    c.text(2 + label_w, y, headline, "white", big, "left", None, scale)

    if show_tv:
        tv = game.broadcast_for(team)
        if tv:
            # Clear the headline's actual height, which doubles at scale 2 --
            # a fixed offset put the broadcast straight through it.
            tv_y = y + big.height * scale + 3
            if tv_y + small.height <= c.height:
                c.text(2, tv_y, tv, dim("grey", 0.85), small, max_width=c.width - 4)


def _when(game, team) -> str:
    """Today's games say the time; later ones say the day as well."""
    if not game.start:
        return "TBD"
    hour = game.start.hour % 12 or 12
    suffix = "A" if game.start.hour < 12 else "P"
    minute = f":{game.start.minute:02d}" if game.start.minute else ""
    return f"{hour}{minute}{suffix}"
