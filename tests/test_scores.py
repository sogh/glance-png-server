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


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Every test here must run off seeded cache files.

    Without this a fixture written to the wrong cache path does not fail -- it
    quietly reaches ESPN instead, and the suite starts depending on the
    network, on the season, and on who is top of the poll this week. That
    happened; hence the guard.

    It patches httpx at each source module, which is the only way out of
    these two. Blocking `socket.socket.connect` does not work -- httpx goes
    through httpcore, which does not call it by that name.
    """
    import glance.sources.espn as espn_mod
    import glance.sources.logos as logos_mod
    import glance.sources.wpbl as wpbl_mod

    def refuse(*args, **kwargs):
        raise AssertionError("this test tried to use the network")

    # logos included: the store fetches on a background thread, so a missing
    # crest here does not fail, it quietly waits on DNS for a fake host and
    # puts seconds on the suite.
    for module in (espn_mod, logos_mod, wpbl_mod):
        monkeypatch.setattr(module.httpx, "get", refuse)


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
                              "displayName": f"{home} Team",
                              "logos": [{"href": f"http://x/{home}.png",
                                         "rel": ["full", "dark"]}]}},
                    {"homeAway": "away", "score": {"value": ascore, "displayValue": str(ascore)},
                     "winner": not winner_home and completed,
                     "curatedRank": {"current": 99},
                     "team": {"abbreviation": away, "shortDisplayName": away,
                              "displayName": f"{away} Team",
                              "logos": [{"href": f"http://x/{away}.png",
                                         "rel": ["full", "dark"]}]}},
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
    ctx.scoreboards = {"ncaa": Board(name="ncaa", source=espn, label="NCAA")}
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
    ctx.scoreboards = {"x": Board(name="x", source=empty)}
    scene = REGISTRY["scores"]
    assert not scene.available(ctx, {"board": "x"})
    assert scene.available(ctx, {"board": "x", "always": True})


# --- following a poll -------------------------------------------------------

def rankings_payload() -> dict:
    def entry(rank, abbrev):
        return {"current": rank, "recordSummary": "2-0",
                "team": {"abbreviation": abbrev, "nickname": abbrev,
                         "logos": [{"href": f"http://x/{abbrev}.png",
                                    "rel": ["full", "dark"]}]}}
    return {"rankings": [
        {"name": "AFCA Coaches Poll", "type": "usa",
         "ranks": [entry(1, "UGA"), entry(2, "TEX"), entry(3, "OSU")]},
        {"name": "AP Top 25", "type": "ap",
         # Deliberately out of order: the source must sort by rank, not trust
         # the order the feed happens to arrive in.
         "ranks": [entry(3, "ND"), entry(1, "TEX"), entry(4, "IU"),
                   entry(2, "UGA"), entry(5, "MIA")]},
    ]}


@pytest.fixture
def polled(tmp_path: Path) -> EspnSource:
    src = EspnSource(league="football/college-football", teams="UGA", top=4,
                     tz=TZ, cache_dir=tmp_path)
    src.rankings_file.write_text(json.dumps(rankings_payload()))
    return src


def test_the_top_of_the_poll_is_read_in_rank_order(polled):
    assert polled.ranked() == ["TEX", "UGA", "ND", "IU"]


def test_a_named_team_that_is_also_ranked_is_followed_once(polled):
    """Georgia sits at #2. Fetching it twice would cost a request and list the
    same game twice."""
    assert polled.teams == ["UGA", "TEX", "ND", "IU"]
    assert polled.teams.count("UGA") == 1


def test_the_named_teams_keep_their_place_as_the_poll_churns(polled):
    assert polled.teams[0] == "UGA"


def test_a_different_poll_can_be_chosen(tmp_path):
    src = EspnSource(league="football/college-football", top=3, poll="usa",
                     tz=TZ, cache_dir=tmp_path)
    src.rankings_file.write_text(json.dumps(rankings_payload()))
    assert src.ranked() == ["UGA", "TEX", "OSU"]


def test_no_top_means_the_poll_is_never_fetched(tmp_path, monkeypatch):
    import glance.sources.espn as mod
    monkeypatch.setattr(mod.httpx, "get",
                        lambda *a, **k: pytest.fail("fetched the poll for top=0"))
    src = EspnSource(league="football/college-football", teams="WASH",
                     tz=TZ, cache_dir=tmp_path)
    assert src.ranked() == []
    assert src.teams == ["WASH"]


def test_a_poll_outage_costs_the_ranked_teams_not_the_panel(polled, monkeypatch):
    import glance.sources.espn as mod
    monkeypatch.setattr(mod.time, "time", lambda: 1e12)      # force it stale
    monkeypatch.setattr(mod.httpx, "get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    # The cached poll still answers ...
    assert polled.teams == ["UGA", "TEX", "ND", "IU"]
    assert "rankings" in polled.last_error


def test_with_no_cached_poll_at_all_the_named_teams_still_work(tmp_path, monkeypatch):
    import glance.sources.espn as mod
    monkeypatch.setattr(mod.httpx, "get",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    src = EspnSource(league="football/college-football", teams="UGA", top=4,
                     tz=TZ, cache_dir=tmp_path)
    assert src.teams == ["UGA"]
    assert src.configured


def test_a_board_following_only_a_poll_is_still_configured(tmp_path):
    src = EspnSource(league="football/college-football", teams="", top=4,
                     tz=TZ, cache_dir=tmp_path)
    assert src.configured


def test_the_board_asks_the_source_every_time(polled):
    """A poll-driven board's membership changes weekly. A copy taken at
    startup would quietly follow last month's top four."""
    board = Board(name="ncaa", source=polled)
    assert board.teams == ["UGA", "TEX", "ND", "IU"]
    polled.fixed = ["WASH"]
    assert board.teams[0] == "WASH"


# --- crests -----------------------------------------------------------------

def crest_store(tmp_path, keys, sizes=(14, 16)):
    """A LogoStore pre-filled with solid squares for `keys`.

    Filled at every size a panel asks for: the scoreline leaves room for names
    and wants 14, the ranking list wants 16, and a store holding only one of
    them silently falls back to text.
    """
    from PIL import Image
    from glance.sources.logos import LogoStore
    store = LogoStore(tmp_path, size=16)
    for key in keys:
        for size in sizes:
            Image.new("RGB", (size, size), (220, 60, 60)).save(
                store._rendered(key, size))
    return store


def finished(espn):
    return [f for f in espn.fixtures(NOW) if f.final][0]


def test_espn_supplies_logo_urls_preferring_the_dark_variant(espn):
    side = finished(espn).home
    assert side.logo == ("http://x/WASH.png",)
    assert side.key == "espn-WASH"


def test_crests_are_drawn_when_both_sides_have_one(app, espn, tmp_path):
    from glance.scenes.scores import _crests
    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = crest_store(tmp_path, ["espn-WASH", "espn-USU"])
    assert _crests(ctx, finished(espn)) is not None


def test_one_crest_and_one_abbreviation_is_not_a_design(app, espn, tmp_path):
    """Mixing them reads as a rendering fault. If either side has no usable
    logo, both sides use text."""
    from glance.scenes.scores import _crests
    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = crest_store(tmp_path, ["espn-WASH"])       # only one of the two
    assert _crests(ctx, finished(espn)) is None


def test_both_logos_are_requested_even_though_one_miss_decides_it(app, espn, tmp_path):
    """Bailing on the first miss queued one download per refresh, so a cold
    cache took a refresh per team to fill instead of one for the pair."""
    from glance.scenes.scores import _crests
    asked: list[str] = []

    class Spy:
        size = 14

        def get(self, key, urls, size=None):
            asked.append(key)
            return None

    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = Spy()
    assert _crests(ctx, finished(espn)) is None
    assert len(asked) == 2


def test_the_scene_falls_back_to_text_with_no_logo_store(app, espn):
    from glance.scenes.scores import _crests
    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = None
    assert _crests(ctx, finished(espn)) is None


def test_logos_can_be_turned_off(app, espn, tmp_path):
    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = crest_store(tmp_path, ["espn-WASH", "espn-USU"])
    ctx.scoreboards = {"ncaa": Board(name="ncaa", source=espn, label="NCAA")}
    with_logos = REGISTRY["scores"].render(ctx, {"board": "ncaa"})
    without = REGISTRY["scores"].render(ctx, {"board": "ncaa", "logos": False})
    assert (with_logos.image.get_flattened_data()
            != without.image.get_flattened_data())


# --- the rankings panel -----------------------------------------------------

def test_the_poll_is_read_as_teams_with_rank_record_and_logo(polled):
    entries = polled.ranked_teams(4)
    assert [s.abbrev for s in entries] == ["TEX", "UGA", "ND", "IU"]
    assert entries[0].rank == 1
    assert entries[0].key == "espn-TEX"


def test_following_is_bounded_by_top_but_the_panel_is_not(polled):
    """Every followed team costs a schedule request, so "show the top 16" on a
    ranking panel must not quietly become sixteen downloads a refresh."""
    polled.top = 2
    assert polled.ranked() == ["TEX", "UGA"]
    assert len(polled.ranked_teams(5)) == 5


def test_a_board_that_follows_nobody_can_still_show_a_poll(tmp_path):
    src = EspnSource(league="football/college-football", teams="", top=0,
                     tz=TZ, cache_dir=tmp_path)
    src.rankings_file.write_text(json.dumps(rankings_payload()))
    assert src.ranked() == []
    assert len(src.ranked_teams(3)) == 3


def rankings_ctx(app, source, logos=None):
    ctx = app.context(NOW, brightness=1.0)
    ctx.scoreboards = {"ncaa": Board(name="ncaa", source=source, label="NCAA")}
    ctx.logos = logos
    return ctx


def test_the_rankings_panel_draws_the_poll(app, polled, tmp_path):
    ctx = rankings_ctx(app, polled, crest_store(tmp_path, ["espn-TEX", "espn-UGA"]))
    scene = REGISTRY["rankings"]
    assert scene.available(ctx, {"board": "ncaa"})
    c = scene.render(ctx, {"board": "ncaa"})
    assert c.image.get_flattened_data().count((0, 0, 0)) < 192 * 32


def test_a_team_with_no_usable_crest_shows_its_abbreviation(app, polled, tmp_path):
    """In a list of many, one text cell reads as a team without a usable
    crest. In a head-to-head it would look like a rendering fault, which is
    why `scores` is all-or-nothing and this is not."""
    ctx = rankings_ctx(app, polled, crest_store(tmp_path, ["espn-TEX"]))
    scene = REGISTRY["rankings"]
    partial = scene.render(ctx, {"board": "ncaa", "style": "crests"})
    # With no store at all every entry is text; with one crest available the
    # panel must differ from that, and still draw something for every team.
    ctx.logos = None
    all_text = scene.render(ctx, {"board": "ncaa", "style": "crests"})
    assert partial.image.get_flattened_data() != all_text.image.get_flattened_data()
    for canvas in (partial, all_text):
        assert canvas.image.get_flattened_data().count((0, 0, 0)) < 192 * 32


def test_text_style_fits_more_than_crests(app, polled, tmp_path):
    ctx = rankings_ctx(app, polled, crest_store(tmp_path, ["espn-TEX", "espn-UGA"]))
    scene = REGISTRY["rankings"]
    crests = scene.render(ctx, {"board": "ncaa", "style": "crests"})
    text = scene.render(ctx, {"board": "ncaa", "style": "text"})
    assert crests.image.get_flattened_data() != text.image.get_flattened_data()


def test_count_limits_what_is_drawn(app, polled, tmp_path):
    ctx = rankings_ctx(app, polled, crest_store(tmp_path, ["espn-TEX", "espn-UGA"]))
    scene = REGISTRY["rankings"]
    one = scene.render(ctx, {"board": "ncaa", "count": 1, "style": "text"})
    five = scene.render(ctx, {"board": "ncaa", "count": 5, "style": "text"})
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if p != (0, 0, 0))
    assert lit(one) < lit(five)


def test_the_rankings_panel_drops_out_with_no_poll(app, tmp_path):
    empty = EspnSource(league="football/college-football", teams="UGA",
                       tz=TZ, cache_dir=tmp_path)
    ctx = rankings_ctx(app, empty)
    scene = REGISTRY["rankings"]
    assert not scene.available(ctx, {"board": "ncaa"})
    assert scene.available(ctx, {"board": "ncaa", "always": True})


def test_a_board_with_no_poll_support_is_handled(app, wpbl):
    """The WPBL has four teams and no poll. Asking it for one must say so,
    not raise."""
    ctx = rankings_ctx(app, wpbl)
    scene = REGISTRY["rankings"]
    assert not scene.available(ctx, {"board": "ncaa"})
    c = scene.render(ctx, {"board": "ncaa"})
    assert c.width == 192


def test_the_crest_scoreline_shows_a_ranking(app, espn, tmp_path):
    """The crest says who, the number says where they stand."""
    from glance.scenes.scores import _result_crests
    from glance.canvas import Canvas
    from glance.fonts import get_font
    fixture = finished(espn)
    from PIL import Image
    crests = [Image.new("RGB", (16, 16), (200, 0, 0))] * 2
    ranked = Canvas(width=192)
    plain = Canvas(width=192)
    _result_crests(ranked, fixture, crests, "amber", get_font("3x5"), "NCAA", True)
    _result_crests(plain, fixture, crests, "amber", get_font("3x5"), "NCAA", False)
    assert fixture.home.rank == 19
    assert ranked.image.get_flattened_data() != plain.image.get_flattened_data()


# --- the crest scoreline layout ---------------------------------------------

def crest_ctx(app, espn, tmp_path):
    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = crest_store(tmp_path, ["espn-WASH", "espn-USU"])
    ctx.scoreboards = {"ncaa": Board(name="ncaa", source=espn, label="NCAA")}
    return ctx


def bands(canvas):
    """The horizontal strips that have any ink in them."""
    rows = [y for y in range(canvas.height)
            if any(canvas.image.getpixel((x, y)) != (0, 0, 0)
                   for x in range(canvas.width))]
    if not rows:
        return []
    out, start, prev = [], rows[0], rows[0]
    for y in rows[1:]:
        if y > prev + 1:
            out.append((start, prev))
            start = y
        prev = y
    out.append((start, prev))
    return out


def test_the_scoreline_stacks_crest_then_name_then_next(app, espn, tmp_path):
    c = REGISTRY["scores"].render(crest_ctx(app, espn, tmp_path), {"board": "ncaa"})
    assert len(bands(c)) == 3, bands(c)
    crest, names, nxt = bands(c)
    assert crest[0] == 0
    assert names[0] > crest[1]
    assert nxt[0] > names[1]


def test_every_row_keeps_clear_of_both_edges(app, espn, tmp_path):
    """The device pans straight from one app into the next, so a pane inked
    end to end has nothing to say where it stops and its neighbour starts."""
    margin = 8
    c = REGISTRY["scores"].render(crest_ctx(app, espn, tmp_path),
                                  {"board": "ncaa", "margin": margin})
    for row in bands(c):
        lit = [x for x in range(c.width) for y in range(row[0], row[1] + 1)
               if c.image.getpixel((x, y)) != (0, 0, 0)]
        assert min(lit) >= margin, f"row {row} runs into the left margin"
        assert max(lit) <= c.width - margin, f"row {row} runs into the right margin"


def test_the_margin_is_a_floor_that_pushes_content_out(app, espn, tmp_path):
    """Narrow content already clears the margin, so the margin only bites on a
    wide row -- where it drops the broadcast rather than run into the gutter."""
    from glance.canvas import Canvas
    from glance.fonts import get_font
    from glance.scenes.scores import _next

    wide = fixture("LAA", "SEA", state=PRE, hours=3)
    wide.broadcast = "ROOT SPORTS NORTHWEST"
    widths = {}
    for margin in (0, 30):
        c = Canvas(width=192)
        _next(c, wide, NOW, 20, "amber", get_font("3x5"), True, True, "", 1,
              align="center", margin=margin)
        lit = [x for x in range(192) for y in range(20, 32)
               if c.image.getpixel((x, y)) != (0, 0, 0)]
        widths[margin] = max(lit) - min(lit)
        assert min(lit) >= margin
        assert max(lit) <= 191 - margin
    assert widths[30] < widths[0], "a tight margin should have shed something"


def test_names_can_be_turned_off(app, espn, tmp_path):
    ctx = crest_ctx(app, espn, tmp_path)
    scene = REGISTRY["scores"]
    with_names = scene.render(ctx, {"board": "ncaa"})
    without = scene.render(ctx, {"board": "ncaa", "names": False})
    assert len(bands(with_names)) == 3
    assert len(bands(without)) == 2


def test_a_name_too_wide_for_its_column_gives_way_to_the_abbreviation():
    """"LOS ANGE..." tells you less than "LA"."""
    from glance.fonts import get_font
    from glance.scenes.scores import name_for

    font = get_font("3x5")
    side = Side("LA", "Los Angeles")
    wide = font.measure("LOS ANGELES")
    assert name_for(side, wide, font) == "LOS ANGELES"
    assert name_for(side, wide - 1, font) == "LA"
    # And nothing is ever half a name.
    assert "…" not in name_for(side, 4, font)


def test_a_team_with_no_long_name_uses_its_abbreviation():
    from glance.fonts import get_font
    from glance.scenes.scores import name_for
    assert name_for(Side("SEA", ""), 999, get_font("3x5")) == "SEA"


def test_a_crest_smaller_than_the_score_does_not_push_the_digits_off_the_top(app, espn, tmp_path):
    """The score is drawn at double height. A 10px crest is shorter than that,
    and centring on the crest alone hung the digits above y=0."""
    ctx = app.context(NOW, brightness=1.0)
    ctx.logos = crest_store(tmp_path, ["espn-WASH", "espn-USU"], sizes=(10, 14))
    ctx.scoreboards = {"ncaa": Board(name="ncaa", source=espn, label="NCAA")}
    scene = REGISTRY["scores"]
    for size in (10, 14):
        c = scene.render(ctx, {"board": "ncaa", "crest": size})
        top = bands(c)[0]
        assert top[0] == 0
        # Three bands means crest+score, names and next are still distinct.
        assert len(bands(c)) == 3, (size, bands(c))


def test_the_board_name_sits_top_left(app, espn, tmp_path):
    """The panel scrolls, so the left edge is read first and the label belongs
    where the eye lands rather than trailing off the far end."""
    scene = REGISTRY["scores"]
    ctx = crest_ctx(app, espn, tmp_path)
    labelled = scene.render(ctx, {"board": "ncaa"})
    bare = scene.render(ctx, {"board": "ncaa", "label": False})

    def ink_in(canvas, x0, x1, y0, y1):
        return sum(1 for x in range(x0, x1) for y in range(y0, y1)
                   if canvas.image.getpixel((x, y)) != (0, 0, 0))

    top = bands(labelled)[0]
    # The label adds ink to the top-left corner and nothing to the top-right.
    assert ink_in(labelled, 0, 34, top[0], top[0] + 6) > ink_in(bare, 0, 34, top[0], top[0] + 6)
    assert ink_in(labelled, 158, 192, top[0], top[0] + 3) == 0


# --- placement and the day word ---------------------------------------------

def test_the_row_stays_balanced_whatever_the_label_says(app):
    """Name, crests and result are one group and the group is centred, so a
    longer board name moves the crests but leaves the two gutters even."""
    from PIL import Image
    from glance.canvas import Canvas
    from glance.fonts import get_font
    from glance.scenes.scores import _result_crests

    crests = [Image.new("RGB", (14, 14), (200, 0, 0))] * 2
    done = fixture("LA", "NY", 7, 9, FINAL)

    for tag in ("WPBL", "MARINERS"):
        c = Canvas(width=192)
        _result_crests(c, done, crests, "amber", get_font("3x5"), tag, True, False)
        lit = [x for x in range(192) for y in range(14)
               if c.image.getpixel((x, y)) != (0, 0, 0)]
        left, right = min(lit), 191 - max(lit)
        assert abs(left - right) <= 3, f"{tag}: gutters {left} vs {right}"


def test_a_long_label_still_never_overlaps_the_crests(app):
    from PIL import Image
    from glance.canvas import Canvas
    from glance.fonts import get_font
    from glance.scenes.scores import _result_crests

    crests = [Image.new("RGB", (14, 14), (200, 0, 0))] * 2
    wide = fixture("AAA", "BBB", 100, 100, FINAL)
    c = Canvas(width=192)
    font = get_font("3x5")
    _result_crests(c, wide, crests, "amber", font, "MARINERS", True, False)
    first = min(x for x in range(192) for y in range(14)
                if c.image.getpixel((x, y)) == (200, 0, 0))
    assert first >= 2 + font.measure("MARINERS") + 6


def test_a_game_today_says_so(app):
    from glance.scenes.scores import day_of
    assert day_of(fixture(hours=3), NOW) == "TODAY"
    assert day_of(fixture(hours=26), NOW) == "TMRW"
    assert day_of(fixture(hours=24 * 3), NOW) in ("WED", "THU", "FRI")
    assert day_of(fixture(hours=24 * 20), NOW).startswith("OCT")


def test_today_used_to_be_blank_and_that_was_the_bug(app):
    """A bare time reads as a fixture on some unstated day, and whether you
    can watch it tonight is the one thing worth knowing."""
    from glance.scenes.scores import day_of
    assert day_of(fixture(hours=3), NOW) != ""


def test_the_day_is_drawn_in_its_own_colour(app):
    from glance.fonts import get_font
    from glance.scenes.scores import _runs

    today = _runs(fixture("LAA", "SEA", state=PRE, hours=3), NOW, True, 1,
                  "amber", "green", False)
    words = dict((t, c) for t, c in today)
    assert "TODAY" in words
    assert words["TODAY"] == "green"
    # The matchup and the time stay white, so the day is what stands out.
    assert [c for t, c in today if t != "TODAY"] == ["white", "white"]


def test_another_day_is_drawn_in_the_accent(app):
    from glance.scenes.scores import _runs
    later = _runs(fixture("DUQ", "WSU", state=PRE, hours=24 * 5), NOW, True, 1,
                  "amber", "green", False)
    day = [c for t, c in later if t not in ("white",)][1]
    assert day == "amber"


def test_the_broadcast_is_dropped_before_the_line_overflows(app):
    """Something has to give on a 192px strip. The broadcast goes first, then
    the day -- the matchup and the time are the part that must survive."""
    from glance.canvas import Canvas
    from glance.fonts import get_font
    from glance.scenes.scores import _next

    long_tv = fixture("LAA", "SEA", state=PRE, hours=3)
    long_tv.broadcast = "A VERY LONG REGIONAL SPORTS NETWORK NAME INDEED"
    c = Canvas(width=192)
    _next(c, long_tv, NOW, 20, "amber", get_font("3x5"), True, True, "", 1,
          align="right")
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(20, 32)]
    assert all(sum(p) == 0 for p in edge), "ran off the right edge"


def test_the_rankings_rows_clear_both_edges(app, polled, tmp_path):
    """Same reason as the scoreline: the device pans one app straight into
    the next, so a pane inked end to end runs into its neighbour."""
    margin = 8
    ctx = rankings_ctx(app, polled, crest_store(tmp_path, ["espn-TEX", "espn-UGA"]))
    for style in ("crests", "text"):
        c = REGISTRY["rankings"].render(
            ctx, {"board": "ncaa", "style": style, "margin": margin})
        for row in bands(c):
            lit = [x for x in range(c.width) for y in range(row[0], row[1] + 1)
                   if c.image.getpixel((x, y)) != (0, 0, 0)]
            assert min(lit) >= margin, f"{style} row {row} hits the left margin"
            assert max(lit) <= c.width - margin, f"{style} row {row} hits the right"


def test_a_short_rankings_row_is_centred_not_left_aligned(app, polled, tmp_path):
    """A row's width is not known until it is full, so packing and drawing in
    one loop pinned everything to the left edge."""
    ctx = rankings_ctx(app, polled, crest_store(tmp_path, ["espn-TEX", "espn-UGA"]))
    c = REGISTRY["rankings"].render(
        ctx, {"board": "ncaa", "style": "text", "count": 2, "label": False})
    lit = [x for x in range(c.width) for y in range(c.height)
           if c.image.getpixel((x, y)) != (0, 0, 0)]
    left, right = min(lit), c.width - 1 - max(lit)
    assert abs(left - right) <= 3, f"gutters {left} vs {right}"
