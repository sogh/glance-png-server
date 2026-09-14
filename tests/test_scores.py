"""Scoreboards: the shared vocabulary, the two providers, and the scene."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from glance.scenes import REGISTRY
from glance.sources.espn import EspnSource
from glance.sources.scores import FINAL, LIVE, PRE, Board, Fixture, Side, pick
from glance.sources.wpbl import WpblSource, acf

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)


def fixture(away="AAA", home="HHH", a=None, h=None, state=PRE, hours=0, **kw) -> Fixture:
    return Fixture(away=Side(away, away, a), home=Side(home, home, h),
                   state=state, start=NOW + timedelta(hours=hours), **kw)


# --- the vocabulary ---------------------------------------------------------

def test_which_side_a_team_is_on():
    f = fixture("WSU", "WASH")
    assert f.side_for("WASH") == "home"
    assert f.side_for("wsu") == "away"          # case-insensitive
    assert f.side_for("OSU") == ""
    assert f.side_for("") == ""


def test_a_score_of_zero_is_a_score_but_a_pending_game_has_none():
    assert fixture(a=0, h=0, state=FINAL).started
    assert not fixture(a=0, h=0, state=PRE).started


def test_who_won_prefers_the_recorded_winner_then_the_score():
    f = fixture("WSU", "WASH", 10, 24, FINAL)
    f.home.winner = True
    assert f.won("WASH") is True
    assert f.won("WSU") is False

    # No winner flag -- a hand-entered feed often has the score first.
    g = fixture("BOS", "SF", 4, 6, FINAL)
    assert g.won("SF") is True
    assert g.won("BOS") is False


def test_who_won_is_unanswerable_before_the_end_or_without_a_score():
    assert fixture("WSU", "WASH", 3, 7, LIVE).won("WASH") is None
    assert fixture("WSU", "WASH", None, None, FINAL).won("WASH") is None
    assert fixture("WSU", "WASH", 1, 2, FINAL).won("OSU") is None


def test_a_rank_is_only_a_rank_inside_the_poll():
    assert Side("WASH", rank=19).ranked
    assert Side("WASH", rank=19).label(True) == "19 WASH"
    assert not Side("WASH", rank=None).ranked
    assert Side("WASH", rank=None).label(True) == "WASH"
    # ESPN's 99-for-unranked is normalised away by the source, but the guard
    # holds anyway: a 99 is not a ranking anyone shows.
    assert not Side("WASH", rank=99).ranked


# --- choosing what to show --------------------------------------------------

def test_live_beats_next_beats_last():
    live = fixture("A", "WASH", 7, 3, LIVE, hours=-1)
    soon = fixture("B", "WASH", state=PRE, hours=5)
    done = fixture("C", "WASH", 1, 2, FINAL, hours=-30)
    snap = pick([done, soon, live], ["WASH"], NOW)
    assert snap["live"] is live and snap["next"] is soon and snap["last"] is done
    # With nothing live, the chosen fixture is the next one, not the old result.
    assert pick([done, soon], ["WASH"], NOW)["next"] is soon


def test_the_most_recent_result_and_the_soonest_fixture_win():
    old = fixture("A", "WASH", 1, 2, FINAL, hours=-200)
    recent = fixture("B", "WASH", 3, 4, FINAL, hours=-20)
    soon = fixture("C", "WASH", state=PRE, hours=2)
    later = fixture("D", "WASH", state=PRE, hours=48)
    snap = pick([old, later, recent, soon], ["WASH"], NOW)
    assert snap["last"] is recent
    assert snap["next"] is soon


def test_a_game_already_under_way_is_not_offered_as_upcoming():
    started = fixture("A", "WASH", state=PRE, hours=-2)
    assert pick([started], ["WASH"], NOW)["next"] is None


def test_the_followed_team_travels_with_each_fixture():
    """Follow two teams and the last result and the next fixture routinely
    belong to different ones. One team on the snapshot would be wrong for at
    least one of them."""
    wash = fixture("USU", "WASH", 14, 16, FINAL, hours=-40)
    wash.home.winner = True
    wsu = fixture("DUQ", "WSU", state=PRE, hours=100)
    snap = pick([wash, wsu], ["WASH", "WSU"], NOW)
    assert snap["last"].following == "WASH"
    assert snap["next"].following == "WSU"
    assert snap["last"].won() is True
    assert snap["next"].mine().abbrev == "WSU"


def test_with_no_teams_configured_the_whole_league_is_followed():
    a = fixture("LA", "NY", 7, 9, FINAL, hours=-40)
    snap = pick([a], [], NOW)
    assert snap["last"] is a
    assert snap["last"].following == ""
    assert snap["last"].mine() is None          # there is no "us"


def test_nothing_to_show_is_none_not_an_empty_shape():
    assert pick([], ["WASH"], NOW) is None
    assert pick([fixture("A", "B")], ["WASH"], NOW) is None


# --- ESPN -------------------------------------------------------------------

def espn_payload() -> dict:
    def event(date, name, away, home, ascore, hscore, status, completed,
              rank=99, tv="BTN", winner_home=False):
        return {
            "date": date, "shortName": name,
            "competitions": [{
                "status": {"type": {"name": status, "completed": completed,
                                    "shortDetail": "Final" if completed else "9/19 - 7:15 PM EDT"}},
                "broadcasts": [{"media": {"shortName": tv}}],
                "competitors": [
                    {"homeAway": "home", "score": {"value": hscore, "displayValue": str(hscore)},
                     "winner": winner_home, "curatedRank": {"current": rank},
                     "record": [{"name": "overall", "summary": "2-0"}],
                     "team": {"abbreviation": home, "shortDisplayName": home,
                              "displayName": f"{home} Team"}},
                    {"homeAway": "away", "score": {"value": ascore, "displayValue": str(ascore)},
                     "winner": not winner_home and completed,
                     "curatedRank": {"current": 99},
                     "team": {"abbreviation": away, "shortDisplayName": away,
                              "displayName": f"{away} Team"}},
                ],
            }],
        }
    return {"team": {"abbreviation": "WASH"}, "events": [
        event("2026-09-12T19:30Z", "USU @ WASH", "USU", "WASH", 14, 16,
              "STATUS_FINAL", True, rank=19, winner_home=True),
        event("2026-09-19T23:15Z", "EWU @ WASH", "EWU", "WASH", 0, 0,
              "STATUS_SCHEDULED", False),
    ]}


@pytest.fixture
def espn(tmp_path: Path) -> EspnSource:
    src = EspnSource(league="football/college-football", teams="WASH",
                     tz=TZ, cache_dir=tmp_path)
    src._cache_file("WASH").write_text(json.dumps(espn_payload()))
    return src


def test_espn_parses_a_season(espn):
    found = espn.fixtures(NOW)
    assert espn.last_error is None
    assert len(found) == 2
    done, nxt = found
    assert (done.away.abbrev, done.away.score) == ("USU", 14)
    assert (done.home.abbrev, done.home.score) == ("WASH", 16)
    assert done.state == FINAL and done.home.winner
    assert done.home.rank == 19 and done.home.record == "2-0"
    assert done.broadcast == "BTN"
    assert nxt.state == PRE


def test_espn_normalises_the_unranked_sentinel(espn):
    """99 means unranked, and drawing it as a ranking would be a lie."""
    assert espn.fixtures(NOW)[0].away.rank is None


def test_espn_drops_the_start_time_from_a_pending_fixture(espn):
    """`shortDetail` on a scheduled game is just the kickoff time, which the
    panel already draws from `start`. Keeping it printed it twice."""
    assert espn.fixtures(NOW)[1].detail == ""
    assert espn.fixtures(NOW)[0].detail == "Final"


def test_espn_start_times_land_in_the_configured_zone(espn):
    done = espn.fixtures(NOW)[0]
    assert done.start.tzinfo is not None
    assert done.start.strftime("%Z") == "PDT"
    assert (done.start.hour, done.start.minute) == (12, 30)   # 19:30Z


def test_espn_does_not_list_the_same_game_twice(tmp_path):
    """Two followed teams playing each other must not appear as two fixtures,
    or the rotation shows the same game back to back."""
    src = EspnSource(league="football/college-football", teams="WASH,USU",
                     tz=TZ, cache_dir=tmp_path)
    for team in ("WASH", "USU"):
        src._cache_file(team).write_text(json.dumps(espn_payload()))
    assert len(src.fixtures(NOW)) == 2


def test_espn_needs_teams_to_be_configured(tmp_path):
    src = EspnSource(league="football/college-football", teams="", cache_dir=tmp_path)
    assert not src.configured
    assert src.fixtures(NOW) == []
    assert "no teams" in src.last_error


def test_espn_serves_stale_data_rather_than_nothing(espn, monkeypatch):
    """A blank panel is worse than yesterday's score."""
    import glance.sources.espn as mod
    monkeypatch.setattr(mod.time, "time", lambda: 1e12)     # force the cache stale
    monkeypatch.setattr(mod.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert len(espn.fixtures(NOW)) == 2
    assert "OSError" in espn.last_error


# --- WPBL -------------------------------------------------------------------

def wrapped(value):
    """ACF wraps every value in its own field definition."""
    return {"value": value, "value_formatted": value,
            "field": {"key": "field_x", "type": "text", "choices": {}}}


def wpbl_games() -> list:
    def game(date, away, home, ascore, hscore, status, time="18:00:00"):
        return {"id": 1, "acf": {
            "game_date": wrapped(date), "game_time": wrapped(time),
            "game_timezone": wrapped("America/Chicago"),
            "game_status": wrapped(status),
            "away_team": wrapped(away), "home_team": wrapped(home),
            "away_score": wrapped(ascore), "home_score": wrapped(hscore),
            "game_broadcast_tv": wrapped(""), "game_broadcast_stream": wrapped("ESPN+"),
        }}
    return [
        game("20260912", "5233", "5222", "9", "7", "final"),
        game("20260914", "5222", "5233", "", "", "scheduled"),
        # The league publishes conditional playoff games with no teams yet.
        game("20260922", "", "", "", "", "scheduled"),
    ]


def wpbl_teams() -> list:
    return [
        {"id": 5233, "slug": "new-york", "title": {"rendered": "New York"},
         "acf": {"team_abbreviation": wrapped("NY")}},
        {"id": 5222, "slug": "los-angeles", "title": {"rendered": "Los Angeles"},
         "acf": {"team_abbreviation": wrapped("LA")}},
    ]


@pytest.fixture
def wpbl(tmp_path: Path) -> WpblSource:
    src = WpblSource(tz=TZ, cache_dir=tmp_path)
    src.games_file.write_text(json.dumps(wpbl_games()))
    src.teams_file.write_text(json.dumps(wpbl_teams()))
    return src


def test_acf_digs_the_value_out_of_its_wrapper():
    node = {"acf": {"home_score": wrapped("7"), "blank": wrapped("")}}
    assert acf(node, "home_score") == "7"
    assert acf(node, "blank") is None
    assert acf(node, "absent") is None
    # A plain value still works, in case the plugin ever stops wrapping.
    assert acf({"acf": {"x": 3}}, "x") == 3


def test_wpbl_parses_games_and_names_the_teams(wpbl):
    found = wpbl.fixtures(NOW)
    assert len(found) == 2          # the placeholder is dropped
    done = found[0]
    assert (done.away.abbrev, done.away.score) == ("NY", 9)
    assert (done.home.abbrev, done.home.score) == ("LA", 7)
    assert done.state == FINAL
    assert done.away.winner and not done.home.winner


def test_wpbl_reads_the_start_time_in_the_parks_own_zone(wpbl):
    """A 6:30pm first pitch in Springfield is 4:30pm here. Reading it as local
    time would shift every game by two hours."""
    nxt = wpbl.fixtures(NOW)[1]
    assert nxt.start.strftime("%Z") == "PDT"
    assert (nxt.start.hour, nxt.start.minute) == (16, 0)     # 18:00 America/Chicago


def test_wpbl_treats_a_missing_score_as_unknown_not_nil(wpbl):
    nxt = wpbl.fixtures(NOW)[1]
    assert nxt.away.score is None and nxt.home.score is None
    assert not nxt.started


def test_wpbl_follows_the_whole_league_by_default(wpbl):
    assert wpbl.configured
    assert wpbl.teams == []
    assert pick(wpbl.fixtures(NOW), wpbl.teams, NOW)["last"] is not None


def test_wpbl_survives_a_team_it_has_never_heard_of(tmp_path):
    src = WpblSource(tz=TZ, cache_dir=tmp_path)
    src.games_file.write_text(json.dumps(wpbl_games()))
    src.teams_file.write_text(json.dumps([]))
    found = src.fixtures(NOW)
    assert len(found) == 2
    assert found[0].away.abbrev == "?"          # drawn as unknown, not crashed


# --- the board and the scene ------------------------------------------------

def test_a_board_turns_a_source_failure_into_no_snapshot(tmp_path):
    class Broken:
        configured, last_error, name = True, None, "x"
        def fixtures(self, now): raise RuntimeError("boom")
    board = Board(name="x", source=Broken())
    assert board.snapshot(NOW) is None
    assert "RuntimeError" in board.last_error


def test_the_scene_draws_a_board(app, espn):
    ctx = app.context(NOW, brightness=1.0)
    ctx.scoreboards = {"ncaa": Board(name="ncaa", source=espn, teams=["WASH"],
                                     label="NCAA")}
    scene = REGISTRY["scores"]
    assert scene.available(ctx, {"board": "ncaa"})
    c = scene.render(ctx, {"board": "ncaa"})
    assert c.width == 192
    text = c.to_ascii()
    assert text.strip(), "nothing drawn"


def test_the_scene_says_so_rather_than_drawing_a_blank(app):
    """An unconfigured or broken board must explain itself on the panel --
    a black rectangle is indistinguishable from a dead device."""
    ctx = app.context(NOW, brightness=1.0)
    ctx.scoreboards = {}
    scene = REGISTRY["scores"]
    assert not scene.available(ctx, {"board": "nope"})
    c = scene.render(ctx, {"board": "nope"})
    assert c.image.get_flattened_data().count((0, 0, 0)) < 192 * 32


def test_the_scene_is_unavailable_with_nothing_to_show_but_always_overrides(app, tmp_path):
    empty = EspnSource(league="football/college-football", teams="ZZZ",
                       tz=TZ, cache_dir=tmp_path)
    empty._cache_file("ZZZ").write_text(json.dumps({"events": []}))
    ctx = app.context(NOW, brightness=1.0)
    ctx.scoreboards = {"x": Board(name="x", source=empty, teams=["ZZZ"])}
    scene = REGISTRY["scores"]
    assert not scene.available(ctx, {"board": "x"})
    assert scene.available(ctx, {"board": "x", "always": True})
