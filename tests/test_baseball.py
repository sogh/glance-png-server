"""MLB scores.

Two things separate this from a naive scoreboard: it shows the broadcast for
the team *you* follow, and it refuses to draw a score before one exists.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from glance.scenes import REGISTRY
from glance.sources.baseball import Game, Side

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 12, 16, 0, tzinfo=TZ)

FEEDS = [
    {"type": "TV", "homeAway": "away", "name": "Mariners.TV"},
    {"type": "TV", "homeAway": "home", "name": "NBCSCA"},
    {"type": "AM", "homeAway": "away", "name": "710 ESPN"},
]


def game(away="SEA", ascore=None, home="ATH", hscore=None, state="Scheduled",
         abstract="Preview", hours=2, inning="", inning_state="",
         winner=None, feeds=None):
    return Game(
        away=Side(away, away, ascore, 78, 70, winner == "away"),
        home=Side(home, home, hscore, 81, 67, winner == "home"),
        state=state, abstract=abstract, start=NOW + timedelta(hours=hours),
        inning=inning, inning_state=inning_state,
        broadcasts=FEEDS if feeds is None else feeds,
    )


# --- where to watch ---------------------------------------------------------

def test_the_broadcast_follows_your_team_not_the_home_side():
    """A Mariners fan watching a road game wants Mariners.TV, not the home
    network. Printing the first listing gets this wrong half the time."""
    g = game()
    assert g.broadcast_for("SEA") == "Mariners.TV"
    assert g.broadcast_for("ATH") == "NBCSCA"


def test_it_falls_back_to_any_tv_then_radio():
    only_home = game(feeds=[{"type": "TV", "homeAway": "home", "name": "NBCSCA"}])
    assert only_home.broadcast_for("SEA") == "NBCSCA"

    radio_only = game(feeds=[{"type": "AM", "homeAway": "away", "name": "710 ESPN"}])
    assert radio_only.broadcast_for("SEA") == "710 ESPN"

    assert game(feeds=[]).broadcast_for("SEA") == ""


def test_a_team_that_is_not_playing_gets_nothing_specific():
    assert game().side_for("NYY") == ""


# --- not drawing scores that do not exist -----------------------------------

def test_a_game_before_first_pitch_has_no_score_to_show():
    """MLB reports 0-0 for a Pre-Game state. Drawing it makes a game that has
    not started look like a scoreless one in progress."""
    assert not game(state="Pre-Game", abstract="Preview", ascore=0, hscore=0).started
    assert game(abstract="Live", ascore=1, hscore=0).started
    assert game(abstract="Final", ascore=5, hscore=6).started


# --- picking what to show ---------------------------------------------------

def snapshot_of(games, now=NOW, teams=("SEA",)):
    """Run the real snapshot logic with the network swapped out.

    `configured` is a property computed from `teams`, so it is set by setting
    those rather than assigned directly.
    """
    from glance.sources.baseball import BaseballSource

    src = BaseballSource.__new__(BaseballSource)
    src.teams = list(teams)
    src.last_error = None
    src._games = lambda _now: games
    return BaseballSource.snapshot(src, now)


def test_a_live_game_outranks_everything():
    snap = snapshot_of([
        game(abstract="Final", hours=-20, ascore=5, hscore=6, winner="home"),
        game(abstract="Live", hours=-1, ascore=4, hscore=2, inning="7th"),
        game(abstract="Preview", hours=6),
    ])
    assert snap["live"] is not None and snap["live"].inning == "7th"


def test_last_and_next_are_both_reported():
    snap = snapshot_of([
        game(abstract="Final", hours=-20, ascore=5, hscore=6, winner="home"),
        game(abstract="Preview", hours=3),
    ])
    assert snap["last"] is not None and snap["next"] is not None
    assert snap["last"].away.score == 5
    assert snap["next"].start > NOW


def test_the_most_recent_final_wins():
    snap = snapshot_of([
        game(abstract="Final", hours=-70, ascore=1, hscore=0, winner="away"),
        game(abstract="Final", hours=-20, ascore=5, hscore=6, winner="home"),
    ])
    assert snap["last"].away.score == 5


def test_a_game_already_started_is_not_offered_as_next():
    snap = snapshot_of([game(abstract="Preview", hours=-3)])
    assert snap["next"] is None


def test_no_teams_configured_is_reported():
    assert snapshot_of([game()], teams=()) is None


# --- rendering --------------------------------------------------------------

class FakeSource:
    configured = True
    last_error = None

    def __init__(self, snap): self._s = snap
    def snapshot(self, now): return self._s
    def game(self, now): return None


def render(app, snap, params=None):
    ctx = app.context(NOW, brightness=1.0)
    ctx.baseball = FakeSource(snap)
    return REGISTRY["baseball"].render(ctx, params or {})


def snap(live=None, last=None, next_=None, team="SEA"):
    return {"team": team, "live": live, "last": last, "next": next_}


def test_last_and_next_render_together(app):
    c = render(app, snap(last=game(abstract="Final", ascore=5, hscore=6,
                                   hours=-20, winner="home"),
                         next_=game(hours=3)))
    assert c.image.size == (192, 32)
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 150


def test_a_live_game_takes_the_whole_panel(app):
    live = render(app, snap(live=game(abstract="Live", ascore=4, hscore=2,
                                      inning="7th", inning_state="Bottom", hours=-1)))
    both = render(app, snap(last=game(abstract="Final", ascore=5, hscore=6,
                                      hours=-20, winner="home"),
                            next_=game(hours=3)))
    assert live.to_ascii() != both.to_ascii()
    greens = [p for p in live.image.get_flattened_data() if p[1] > 120 and p[0] < 90]
    assert greens, "the inning should read live"


def test_a_win_and_a_loss_look_different(app):
    won = render(app, snap(last=game(abstract="Final", ascore=8, hscore=2,
                                     hours=-20, winner="away")))
    lost = render(app, snap(last=game(abstract="Final", ascore=5, hscore=6,
                                      hours=-20, winner="home")))
    assert won.to_ascii() != lost.to_ascii()


def test_nothing_overflows(app):
    for params in ({}, {"broadcast": False}):
        c = render(app, snap(last=game(abstract="Final", ascore=12, hscore=11,
                                       hours=-20, winner="away"),
                             next_=game(hours=30)), params)
        edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
        assert all(sum(p) == 0 for p in edge)


def test_the_broadcast_never_draws_through_the_headline(app):
    """A fixed offset put it straight through the scale-2 version."""
    c = render(app, snap(next_=game(hours=6)))
    assert c.image.size == (192, 32)
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 100


def test_no_data_explains_itself(app):
    ctx = app.context(NOW, brightness=1.0)
    ctx.baseball = FakeSource(None)
    c = REGISTRY["baseball"].render(ctx, {})
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 0


def test_it_drops_out_of_rotation_with_no_source(app, now):
    ctx = app.context(now)
    ctx.baseball = None
    assert not REGISTRY["baseball"].available(ctx, {})
    assert REGISTRY["baseball"].available(ctx, {"always": True})
