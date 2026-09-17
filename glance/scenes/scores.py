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
from ..layout import centre
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
    """'TODAY', 'TMRW', 'SAT' later this week, 'SEP 19' beyond that.

    Today used to render as an empty string, on the reasoning that a bare time
    obviously means today. It does not: "AT LAA 6:38P" reads as a fixture on
    some unstated day, and the one thing worth knowing about a game is whether
    you can watch it tonight.
    """
    if not fixture.start:
        return ""
    days = (fixture.start.date() - now.date()).days
    if days <= 0:
        return "TODAY"
    if days == 1:
        return "TMRW"
    if days < 7:
        return fixture.start.strftime("%a").upper()
    return fixture.start.strftime("%b %-d").upper()


def _runs(fixture, now, show_rank, following, accent, today_colour, show_tv):
    """The next-fixture line as coloured runs.

    The day is drawn in its own colour so it separates from the matchup and
    the time without any punctuation -- at this size a separator costs as much
    width as a word.
    """
    mine, opponent = fixture.mine(), fixture.opponent()
    if opponent is None or following == 0:
        # Following the whole league: there is no "us", so name both sides.
        matchup = f"{fixture.away.label(show_rank)} V {fixture.home.label(show_rank)}"
    else:
        # "AT"/"VS" rather than "@": the at-sign is a dense knot of pixels at
        # this size and reads as a smudge, where two letters are unambiguous.
        at = "AT" if fixture.side_for() == "away" else "VS"
        # With more than one team followed, "AT DUQ" does not say who is
        # playing -- the last result and the next fixture routinely belong to
        # different teams.
        who = f"{mine.abbrev} " if following > 1 and mine is not None else ""
        matchup = f"{who}{at} {opponent.label(show_rank)}"

    out = [(matchup, "white")]
    day = day_of(fixture, now)
    if day:
        out.append((day, today_colour if day == "TODAY" else accent))
    out.append((clock(fixture), "white"))
    if show_tv and fixture.broadcast:
        out.append((fixture.broadcast, dim("grey", 0.85)))
    return out


def _measure_runs(runs, font, gap: int) -> int:
    return sum(font.measure(t) for t, _ in runs) + gap * (len(runs) - 1)


def _draw_runs(c, x: int, y: int, runs, font, gap: int, scale: int = 1) -> int:
    for text, colour in runs:
        x += c.text(x, y, text, colour, font, "left", None, scale) + gap
    return x


@register("scores", available=_available,
          description="Score and next fixture from a configured scoreboard",
          params=[
              Param("board", "select", None, options="@boards",
                    help="Which configured scoreboard to read"),
              Param("accent", "color", "amber", options="@colors"),
              Param("label", "bool", True, help="Show the league name"),
              Param("broadcast", "bool", True, help="Show where to watch"),
              Param("rank", "bool", True, help="Show poll rankings where there are any"),
              Param("logos", "bool", True,
                    help="Draw team logos when they read at this size"),
              Param("crest", "number", 14, minimum=8, maximum=24,
                    help="Crest size on the scoreline"),
              Param("names", "bool", True, help="Short team names under the scores"),
              Param("today_color", "color", "green", options="@colors",
                    help="Colour for TODAY on the next-fixture line"),
              Param("margin", "number", 8, minimum=0, maximum=40,
                    help="Blank kept at each edge, so the pane separates from "
                         "its neighbours as the device pans past"),
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

    size = int(params.get("crest", 14) or 14)
    margin = max(0, int(params.get("margin", 8) or 0))
    names = bool(params.get("names", True))
    use_logos = bool(params.get("logos", True))

    if snap["live"]:
        return _live(c, snap["live"],
                     _crests(ctx, snap["live"], size) if use_logos else None,
                     accent, small, show_tv, tag, show_rank, names, margin)

    crests = _crests(ctx, snap["last"], size) if use_logos else None

    y, align = 2, "left"
    if snap["last"] and crests:
        # The crest block is far taller than a line of text, so it displaces
        # the scoreline rather than sharing its 5px strip, and what follows
        # sits under it and to the right -- the result reads first, the next
        # fixture second.
        y = _result_crests(c, snap["last"], crests, accent, small, tag,
                           show_rank, names, margin)
        align = "center"
    elif snap["last"]:
        _result(c, snap["last"], ctx.now, y, accent, small, tag, show_rank)
        y += 11
    if snap["next"]:
        _next(c, snap["next"], ctx.now, y, accent, small, show_tv, show_rank,
              tag if not snap["last"] else "", following, align,
              str(params.get("today_color", "green")), margin)
    elif snap["last"] and show_tv and snap["last"].broadcast:
        c.text(2, y + 2, snap["last"].broadcast, dim("grey", 0.85), small,
               max_width=c.width - 4)
    return c


def _matchup(side, show_rank: bool) -> str:
    return f"{side.label(show_rank)} {'' if side.score is None else side.score}".strip()


def _live(c, fixture, crests, accent, small, show_tv, tag, show_rank,
          names=True, margin=8):
    """A game in progress.

    The same card as a finished one -- crests, scores, names -- with the half
    inning in green where the result would go. It used to be a separate
    layout, a wide line of plain text with no crest and no name on it, so the
    one panel you actually stand and watch was the one that looked least like
    the others.
    """
    if crests:
        y = _result_crests(c, fixture, crests, accent, small, tag, show_rank,
                           names, margin)
        runs = [(fixture.detail or "LIVE", "green")]
        if show_tv and fixture.broadcast:
            runs.append((fixture.broadcast, dim("grey", 0.85)))
        gap = 4
        while len(runs) > 1 and _measure_runs(runs, small, gap) > c.width - 2 * margin:
            runs.pop()
        width = _measure_runs(runs, small, gap)
        _draw_runs(c, centre(c.width, width, margin), y, runs, small, gap)
        return c

    # No usable crest for one of the sides: the wide scoreline, but centred
    # inside the margins like everything else.
    big = get_font("5x7")
    text = (f"{_matchup(fixture.away, show_rank)}  "
            f"{_matchup(fixture.home, show_rank)}")
    room = c.width - 2 * margin
    scale = 2 if big.measure(text) * 2 <= room else 1
    c.centered(text, "white", big, y=4, max_width=room, scale=scale)

    runs = [(fixture.detail or "LIVE", "green")]
    if show_tv and fixture.broadcast:
        runs.append((fixture.broadcast, dim("grey", 0.85)))
    elif tag:
        runs.append((tag, dim("grey", 0.9)))
    gap = 4
    while len(runs) > 1 and _measure_runs(runs, small, gap) > room:
        runs.pop()
    width = _measure_runs(runs, small, gap)
    _draw_runs(c, centre(c.width, width, margin), 23, runs, small, gap)
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


def _crests(ctx, fixture, size=None):
    """Both logos, or nothing.

    All or nothing on purpose: one crest beside one abbreviation reads as a
    rendering fault rather than as a design. If either side has no logo that
    survives the reduction -- see sources/logos.py -- both sides use text.
    """
    store = getattr(ctx, "logos", None)
    if store is None or fixture is None:
        return None
    # Ask for both before judging. Returning early on the first miss would
    # only ever queue one download per refresh, so a fresh cache took a
    # refresh per team to fill instead of one for the pair.
    pair = [store.get(side.key or side.abbrev, side.logo, size) if side.logo else None
            for side in (fixture.away, fixture.home)]
    return pair if all(p is not None for p in pair) else None


def _result_crests(c, fixture, crests, accent, small, tag, show_rank=True,
                   names=True, margin=8):
    """The finished game as two crests, two scores and two names.

    Returns the y the next line should start at. Each team is one column --
    rank, crest, score on top, name centred underneath -- because a name
    hanging off the side of its own crest belongs to nobody in particular.

    The board name, the crests and the result are laid out as one group and
    that group is centred, rather than the name being pinned to the left edge
    and the result to the right. Pinned to the edges the pane is inked from
    end to end, and on a device that pans straight from one app into the next
    there is nothing to say where one stops and the other starts.
    """
    big = get_font("5x7")
    size = crests[0].height
    top = 0
    gap = 3                 # crest to its own score
    between = 14            # one team to the other
    # The score is drawn at double height, which is taller than a small crest.
    # The row is as tall as whichever wins, and both are centred in it, or a
    # 10px crest leaves the digits hanging off the top of the panel.
    row = max(size, big.height * 2)

    sides = (fixture.away, fixture.home)
    ranks = [str(s.rank) if show_rank and s.ranked else "" for s in sides]
    lead = [small.measure(r) + 2 if r else 0 for r in ranks]
    widths = [big.measure("" if s.score is None else str(s.score)) * 2 for s in sides]
    columns = [pad + size + gap + w for pad, w in zip(lead, widths)]
    block = sum(columns) + between

    won = fixture.won()
    label = tag[:8] if tag else ""
    lead_w = (small.measure(label) + 8) if label else 0
    trail_w = (small.measure("W") + 8) if won is not None else 0

    # One group: name, crests, result. Centred together, so the blank left
    # over lands at the two edges where it does some good.
    x = centre(c.width, lead_w + block + trail_w, margin)
    if label:
        c.text(x, top + (row - small.height) // 2, label, dim(accent, 0.75), small)
    x += lead_w
    crest_left = x

    for side, crest, width, rank, pad, column in zip(sides, crests, widths,
                                                     ranks, lead, columns):
        left = x
        if rank:
            c.text(x, top + (row - small.height) // 2, rank, dim(accent, 0.85), small)
            x += pad
        c.blit(crest, x, top + (row - size) // 2)
        x += size + gap
        if side.score is not None:
            colour = ("green" if side.winner
                      else dim("white", 0.55) if _has_winner(fixture)
                      else "white")
            c.text(x, top + (row - big.height * 2) // 2, str(side.score),
                   colour, big, "left", None, 2)
        x += width

        if names:
            # A name may lean into the gap either side of its column; at this
            # size "Washington" does not fit inside 39 pixels and clipping it
            # to "Washingt" helps nobody.
            room = column + between - 4
            c.text(left + column // 2, top + row + 1, name_for(side, room, small),
                   dim("white", 0.8), small, "center", room)
        x += between

    if won is not None:
        c.text(crest_left + block + 8, top + (row - small.height) // 2,
               "W" if won else "L",
               "green" if won else dim("white", 0.55), small)
    return row + (small.height + 3 if names else 2)


def name_for(side, room: int, font) -> str:
    """The name to put under a crest.

    The short name if it fits, otherwise the abbreviation -- "LOS ANGE..."
    tells you less than "LA", so a name that will not fit gives way entirely
    rather than being cut off.
    """
    name = (side.name or "").strip().upper()
    if name and font.measure(name) <= room:
        return name
    return side.abbrev.upper()


def _next(c, fixture, now, y, accent, small, show_tv, show_rank, tag,
          following, align="left", today_colour="green", margin=8):
    """The next fixture: when, against whom, and where to watch."""
    big = get_font("5x7")
    label = tag or "NEXT"
    label_w = small.measure(label) + 5

    if align == "center":
        # Under the crests and centred with them. One line, so the broadcast
        # joins it rather than claiming a row of its own there is no room for.
        runs = _runs(fixture, now, show_rank, following, accent, today_colour, show_tv)
        gap = 4
        room = c.width - 2 * margin - label_w
        # Drop the broadcast, then the day, rather than letting the line run
        # into the margins -- the gutter is the point.
        while len(runs) > 1 and _measure_runs(runs, small, gap) > room:
            runs.pop()
        width = label_w + _measure_runs(runs, small, gap)
        left = centre(c.width, width, margin)
        c.text(left, y, label, dim(accent, 0.8), small)
        _draw_runs(c, left + label_w, y, runs, small, gap)
        return

    runs = _runs(fixture, now, show_rank, following, accent, today_colour, False)
    gap = 5
    c.text(2, y + 2, label, dim(accent, 0.8), small)
    _draw_runs(c, 2 + label_w, y, runs, big, gap)

    if show_tv and fixture.broadcast:
        tv_y = y + big.height + 3
        if tv_y + small.height <= c.height:
            c.text(2, tv_y, fixture.broadcast, dim("grey", 0.85), small,
                   max_width=c.width - 4)
