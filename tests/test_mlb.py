"""MLB in the shared scoreboard vocabulary."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from glance.sources.mlb import LOGO_SLUG, MlbSource, logos_for
from glance.sources.scores import FINAL, LIVE, PRE, pick

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import glance.sources.baseball as mod

    def refuse(*args, **kwargs):
        raise AssertionError("this test tried to use the network")

    monkeypatch.setattr(mod.httpx, "get", refuse)


def game(away, home, away_score, home_score, state, start, *, inning="",
         inning_state="", winner=None):
    def side(abbrev, score, wins, losses):
        node = {"team": {"abbreviation": abbrev, "teamName": f"{abbrev} Team"},
                "leagueRecord": {"wins": wins, "losses": losses}}
        if score is not None:
            node["score"] = score
        node["isWinner"] = winner == abbrev
        return node
    return {
        "gameDate": start.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": {"detailedState": state, "abstractGameState": state},
        "linescore": {"currentInningOrdinal": inning, "inningState": inning_state},
        "teams": {"away": side(away, away_score, 70, 80),
                  "home": side(home, home_score, 61, 89)},
        "broadcasts": [
            {"type": "TV", "homeAway": "home", "name": "NBCS-CA"},
            {"type": "TV", "homeAway": "away", "name": "Mariners.TV"},
        ],
    }


@pytest.fixture
def mlb(tmp_path: Path) -> MlbSource:
    src = MlbSource(teams="SEA", tz=TZ, cache_dir=tmp_path)
    payload = {"dates": [{"games": [
        game("SEA", "ATH", 7, 8, "Final", NOW - timedelta(days=1), winner="ATH"),
        game("SEA", "LAA", None, None, "Preview", NOW + timedelta(hours=6)),
    ]}]}
    src.inner.cache_file.write_text(json.dumps(payload))
    return src


# --- logos ------------------------------------------------------------------

def test_logos_are_addressed_by_the_lowercase_abbreviation():
    assert logos_for("SEA")[0].endswith("/500-dark/sea.png")
    assert logos_for("SEA")[1].endswith("/500/sea.png")


def test_the_dark_variant_is_preferred():
    assert "-dark" in logos_for("NYY")[0]


def test_the_one_abbreviation_the_two_apis_disagree_on():
    """statsapi and ESPN agree on 29 of 30. Arizona is the exception, and
    without the mapping its crest 404s."""
    assert LOGO_SLUG == {"AZ": "ari"}
    assert logos_for("AZ")[0].endswith("/ari.png")


# --- adaptation -------------------------------------------------------------

def test_games_become_fixtures(mlb):
    found = mlb.fixtures(NOW)
    assert len(found) == 2
    done, nxt = found
    assert (done.away.abbrev, done.away.score) == ("SEA", 7)
    assert (done.home.abbrev, done.home.score) == ("ATH", 8)
    assert done.state == FINAL and done.home.winner
    assert nxt.state == PRE


def test_a_record_comes_through_as_wins_and_losses(mlb):
    assert mlb.fixtures(NOW)[0].away.record == "70-80"


def test_the_broadcast_is_the_one_our_fan_would_turn_on(mlb):
    """Every game lists a feed for both sides. A Mariners fan watching a road
    game wants Mariners.TV, not the home network -- printing the first listing
    in the array is wrong half the time."""
    for fixture in mlb.fixtures(NOW):
        assert fixture.broadcast == "Mariners.TV"


def test_the_half_inning_shows_only_while_a_game_is_being_played(tmp_path):
    src = MlbSource(teams="SEA", tz=TZ, cache_dir=tmp_path)
    src.inner.cache_file.write_text(json.dumps({"dates": [{"games": [
        game("SEA", "ATH", 3, 2, "Live", NOW - timedelta(hours=1),
             inning="7th", inning_state="Top"),
    ]}]}))
    live = src.fixtures(NOW)[0]
    assert live.state == LIVE
    assert live.detail == "TOP 7th"


def test_a_pending_game_has_no_score_rather_than_nil(mlb):
    """statsapi reports 0-0 before first pitch, and drawing that makes a game
    that has not started look like a scoreless one in progress."""
    nxt = mlb.fixtures(NOW)[1]
    assert nxt.away.score is None and nxt.home.score is None
    assert not nxt.started


def test_the_usual_priority_still_holds(mlb):
    snap = pick(mlb.fixtures(NOW), mlb.teams, NOW)
    assert snap["last"].home.abbrev == "ATH"
    assert snap["next"].home.abbrev == "LAA"
    assert snap["last"].won() is False


def test_it_needs_teams(tmp_path):
    src = MlbSource(teams="", tz=TZ, cache_dir=tmp_path)
    assert not src.configured
    assert src.fixtures(NOW) == []
    assert "no teams" in src.last_error
