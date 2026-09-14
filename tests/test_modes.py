"""Modes: a calendar event that changes what the panels show, while it runs."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from glance.carousel import matches_when
from glance.runtime import GlanceApp
from glance.sources.modes import Mode, ModeSet

TZ = ZoneInfo("America/Los_Angeles")


# --- matching ---------------------------------------------------------------

def test_a_mode_defaults_to_its_own_name_as_a_tag():
    mode = Mode(name="visitors")
    assert mode.match == ["#visitors"]
    assert mode.matches("Farm tour #visitors")
    assert not mode.matches("Farm tour")


def test_tags_match_anywhere_in_the_title_and_ignore_case():
    mode = Mode(name="visitors")
    assert mode.matches("#VISITORS")
    assert mode.matches("Sunday open day #Visitors please")
    assert not mode.matches("visitors")          # no hash, not a tag
    assert not mode.matches("#visitorship")      # word-bounded


def test_a_bare_phrase_matches_on_word_boundaries():
    mode = Mode(name="visitors", match=["open house"])
    assert mode.matches("Open House 2pm")
    assert mode.matches("2pm OPEN HOUSE")
    # The whole point of the boundary: a phrase buried inside other words is
    # not what anyone meant.
    assert not mode.matches("reopen household budget")


def test_several_terms_are_any_of():
    mode = Mode(name="visitors", match=["#visitors", "open house", "farm tour"])
    for title in ("Thing #visitors", "Open house", "Farm Tour with the school"):
        assert mode.matches(title), title
    assert not mode.matches("Ordinary Tuesday")


def test_an_empty_or_blank_term_is_ignored_not_matched_against_everything():
    """A stray empty string in config must not turn the mode permanently on."""
    mode = Mode(name="visitors", match=["", "   ", "#visitors"])
    assert not mode.matches("Ordinary Tuesday")
    assert mode.matches("Thing #visitors")


def test_config_shorthands():
    assert ModeSet({"a": "#a", "b": ["#b", "bee"], "c": {"match": "#c"}}).names == ["a", "b", "c"]
    assert ModeSet({"off": {"match": "#off", "enabled": False}}).names == []
    assert ModeSet({}).names == []
    assert not ModeSet(None)


def test_tag_words_are_collected_for_the_calendar_to_strip():
    modes = ModeSet({"visitors": {"match": ["#visitors", "open house"]},
                     "quiet": {"match": ["#hushed"]}})
    # Bare phrases are not tags and must not be stripped out of titles.
    assert modes.tag_words == frozenset({"visitors", "hushed"})


# --- the `when` condition ---------------------------------------------------

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)


def test_mode_conditions():
    on = frozenset({"visitors"})
    assert matches_when({"mode": "visitors"}, NOW, on)
    assert not matches_when({"mode": "visitors"}, NOW, frozenset())
    assert not matches_when({"not_mode": "visitors"}, NOW, on)
    assert matches_when({"not_mode": "visitors"}, NOW, frozenset())


def test_mode_accepts_a_list_or_a_comma_string_and_means_any_of():
    on = frozenset({"party"})
    assert matches_when({"mode": ["visitors", "party"]}, NOW, on)
    assert matches_when({"mode": "visitors,party"}, NOW, on)
    assert not matches_when({"mode": ["visitors", "harvest"]}, NOW, on)


def test_mode_combines_with_the_time_window():
    on = frozenset({"visitors"})
    when = {"mode": "visitors", "hours": {"from": 9, "to": 17}}
    assert matches_when(when, NOW, on)
    assert not matches_when(when, NOW.replace(hour=3), on)
    assert not matches_when(when, NOW, frozenset())


def test_an_entry_with_no_condition_is_unaffected_by_modes():
    assert matches_when({}, NOW, frozenset({"visitors"}))


# --- end to end -------------------------------------------------------------

def ics(*events: str) -> str:
    return ("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//test//EN\n"
            + "".join(events) + "END:VCALENDAR\n")


def event(uid: str, summary: str, start: datetime, hours: int = 3) -> str:
    end = start + timedelta(hours=hours)
    return (f"BEGIN:VEVENT\nUID:{uid}@test\n"
            f"DTSTART;TZID=America/Los_Angeles:{start:%Y%m%dT%H%M%S}\n"
            f"DTEND;TZID=America/Los_Angeles:{end:%Y%m%dT%H%M%S}\n"
            f"SUMMARY:{summary}\nEND:VEVENT\n")


VISIT_DAY = datetime(2026, 9, 14, 13, 0, tzinfo=TZ)


@pytest.fixture
def farm(tmp_path: Path) -> GlanceApp:
    """A project whose `today` channel hands its slot to a banner on demand."""
    (tmp_path / "config").mkdir()
    (tmp_path / "data" / "cache").mkdir(parents=True)
    (tmp_path / "config" / "settings.yaml").write_text(yaml.safe_dump({
        "timezone": "America/Los_Angeles",
        "panel": {"width": 192},
        "carousel": {"mode": "advance", "min_advance_interval": 0},
        "paths": {"state_file": str(tmp_path / "data" / "state.json"),
                  "overlay_file": str(tmp_path / "data" / "overrides.json"),
                  "cache_dir": str(tmp_path / "data" / "cache"),
                  "static_dir": str(tmp_path / "assets" / "static")},
        "sources": {"calendars": {"agenda": {"url": "http://feed.invalid/farm.ics"}}},
        "modes": {"visitors": {"match": ["#visitors", "open house"]}},
        "channels": {"today": [
            {"scene": "banner", "takeover": True, "when": {"mode": "visitors"},
             "params": {"title": "MAPLE FARM", "subtitle": "WELCOME"}},
            {"scene": "agenda", "params": {"always": True}},
        ]},
    }))
    app = GlanceApp.from_config(tmp_path / "config" / "settings.yaml")
    # Seed the cache rather than stand up a server: the fetch path has its own
    # tests, and what is under test here is what happens to the events after.
    app.calendars.sources["agenda"].cache_file.write_text(ics(
        event("visit", "Farm tour #visitors", VISIT_DAY),
        event("hidden", "Open house #hide", VISIT_DAY + timedelta(days=1)),
        event("normal", "Dentist", VISIT_DAY + timedelta(days=2)),
    ))
    return app


def test_the_mode_is_on_only_while_the_event_runs(farm):
    before = farm.context(VISIT_DAY - timedelta(hours=1))
    during = farm.context(VISIT_DAY + timedelta(hours=1))
    after = farm.context(VISIT_DAY + timedelta(hours=4))
    assert before.modes == frozenset()
    assert during.modes == frozenset({"visitors"})
    assert after.modes == frozenset()


def test_the_banner_takes_the_channel_over_and_gives_it_back(farm):
    during = farm.carousel.select("today", farm.context(VISIT_DAY + timedelta(hours=1)))
    after = farm.carousel.select("today", farm.context(VISIT_DAY + timedelta(hours=4)))
    assert during.entry.ref == "banner"
    assert during.takeover
    assert after.entry.ref == "agenda"


def test_a_hidden_event_still_arms_the_mode(farm):
    """Keeping the trigger off the agenda is a reasonable thing to want, and
    it would be baffling if that also silently stopped the mode."""
    ctx = farm.context(VISIT_DAY + timedelta(days=1, hours=1))
    assert ctx.modes == frozenset({"visitors"})


def test_the_mode_tag_is_stripped_from_the_title(farm):
    ctx = farm.context(VISIT_DAY + timedelta(hours=1))
    summaries = [e.summary for e in ctx.calendars.upcoming(ctx.now)]
    assert "Farm tour" in summaries
    assert not any("#visitors" in s for s in summaries)


def test_modes_are_worked_out_once_per_request(farm):
    ctx = farm.context(VISIT_DAY + timedelta(hours=1))
    calls = []
    real = farm.modes.active
    ctx.mode_set = type("Spy", (), {"active": lambda _s, n, c: (calls.append(1), real(n, c))[1]})()
    assert ctx.modes == frozenset({"visitors"})
    assert ctx.modes == frozenset({"visitors"})
    assert len(calls) == 1


def test_an_unreadable_calendar_means_no_modes_not_a_crash(farm):
    farm.calendars.sources["agenda"].cache_file.write_text("not an ical document")
    ctx = farm.context(VISIT_DAY + timedelta(hours=1))
    assert ctx.modes == frozenset()
    assert farm.carousel.select("today", ctx) is not None


def test_status_reports_what_is_on(farm):
    body = farm.status()
    assert "visitors" in body["modes"]["configured"]
    assert body["modes"]["configured"]["visitors"]["match"] == ["#visitors", "open house"]


# --- banners ----------------------------------------------------------------

def test_a_spanned_banner_is_laid_out_once_and_cut(app):
    """Each slice must be a window onto one wide layout. Laying each out on
    its own would put a second copy of the title in the second panel."""
    whole = app.render_scene("banner", {"title": "MAPLE FARM", "span": 2,
                                        "part": 1}, brightness=1.0)[0]
    second = app.render_scene("banner", {"title": "MAPLE FARM", "span": 2,
                                         "part": 2}, brightness=1.0)[0]
    assert whole.width == second.width == 192
    assert whole.image.get_flattened_data() != second.image.get_flattened_data()

    # Join the halves back up and it must equal a single 384-wide render.
    from glance.canvas import Canvas
    joined = Canvas(width=384)
    joined.image.paste(whole.image, (0, 0))
    joined.image.paste(second.image, (192, 0))
    ctx = app.context(brightness=1.0)
    ctx.width_override = 384
    from glance.scenes import REGISTRY
    full = REGISTRY["banner"].render(ctx, {"title": "MAPLE FARM", "span": 1})
    assert joined.image.get_flattened_data() == full.image.get_flattened_data()


def test_span_is_capped_at_what_the_canvas_allows(app):
    c = app.render_scene("banner", {"title": "HI", "span": 9, "part": 9},
                         brightness=1.0)[0]
    assert c.width == 192


def test_an_unspanned_banner_ignores_part(app):
    a = app.render_scene("banner", {"title": "HI"}, brightness=1.0)[0]
    b = app.render_scene("banner", {"title": "HI", "part": 2}, brightness=1.0)[0]
    assert a.image.get_flattened_data() == b.image.get_flattened_data()


def test_the_title_never_collides_with_the_rules(app):
    """The scale picker checks height as well as width; without that a short
    title grew until it overwrote the top rule."""
    c = app.render_scene("banner", {"title": "OPEN HOUSE", "subtitle": "COME IN",
                                    "motif": "rules", "accent": "mint"},
                         brightness=1.0)[0]
    px = c.image.load()
    accent = px[0, 0]
    for x in range(c.width):            # the rules themselves stay intact
        assert px[x, 0] == accent
        assert px[x, c.height - 1] == accent


def test_a_banner_with_no_subtitle_centres_the_title(app):
    c = app.render_scene("banner", {"title": "WELCOME", "motif": "none"},
                         brightness=1.0)[0]
    rows = [y for y in range(c.height)
            if any(c.image.getpixel((x, y)) != (0, 0, 0) for x in range(c.width))]
    assert rows, "nothing drawn"
    assert abs((rows[0]) - (c.height - 1 - rows[-1])) <= 1
