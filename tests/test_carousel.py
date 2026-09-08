from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from glance.carousel import Carousel, matches_when
from glance.config import load_settings

TZ = ZoneInfo("America/Los_Angeles")


def keys(app, when, n, advance=True):
    app.carousel.min_advance_interval = 0
    return [app.carousel.select("main", app.context(when), advance=advance).key for _ in range(n)]


# --- when conditions --------------------------------------------------------

def test_empty_condition_always_matches():
    assert matches_when({}, datetime(2026, 12, 25, 3, 0))


def test_month_weekday_and_date_conditions():
    xmas = datetime(2026, 12, 25, 20, 30)          # a Friday
    assert matches_when({"months": [12]}, xmas)
    assert not matches_when({"months": [1, 2]}, xmas)
    assert matches_when({"weekdays": ["fri"]}, xmas)
    assert not matches_when({"weekdays": ["mon"]}, xmas)
    assert matches_when({"dates": ["12-25"]}, xmas)
    assert not matches_when({"dates": ["12-24"]}, xmas)


def test_hour_range_and_wrapping_midnight():
    assert matches_when({"hours": {"from": 7, "to": 22}}, datetime(2026, 1, 1, 9))
    assert not matches_when({"hours": {"from": 7, "to": 22}}, datetime(2026, 1, 1, 3))
    night = {"hours": {"from": 22, "to": 6}}
    assert matches_when(night, datetime(2026, 1, 1, 23))
    assert matches_when(night, datetime(2026, 1, 1, 2))
    assert not matches_when(night, datetime(2026, 1, 1, 12))


def test_explicit_hour_list_and_minute_bounds():
    assert matches_when({"hours": [8, 9]}, datetime(2026, 1, 1, 9, 59))
    assert not matches_when({"hours": [8, 9]}, datetime(2026, 1, 1, 10))
    assert matches_when({"from": "09:30", "to": "17:00"}, datetime(2026, 1, 1, 9, 30))
    assert not matches_when({"from": "09:30"}, datetime(2026, 1, 1, 9, 29))


def test_all_conditions_must_hold_together():
    assert not matches_when({"months": [12], "weekdays": ["mon"]}, datetime(2026, 12, 25, 9))


# --- rotation ---------------------------------------------------------------

def test_rotation_cycles_through_available_scenes(app, now):
    assert keys(app, now, 6) == [
        "todos(count=3)", "clock", "todos(count=3)",
        "clock", "todos(count=3)", "clock",
    ]


def test_scenes_with_nothing_to_show_are_skipped(app, now):
    """The holiday entry is first in config but not active in September."""
    assert "holiday" not in keys(app, now, 4)


def test_takeover_pre_empts_the_whole_rotation(app):
    xmas_eve = datetime(2026, 12, 20, 9, 0, tzinfo=TZ)
    assert keys(app, xmas_eve, 3) == ["holiday", "holiday", "holiday"]


def test_takeover_does_not_disturb_where_the_rotation_had_got_to(app, now):
    app.carousel.min_advance_interval = 0
    assert app.carousel.select("main", app.context(now)).key == "todos(count=3)"

    xmas = datetime(2026, 12, 20, 9, 0, tzinfo=TZ)
    for _ in range(3):
        app.carousel.select("main", app.context(xmas))

    # Back in September the rotation resumes from todos, not from wherever the
    # takeover left things.
    assert app.carousel.select("main", app.context(now)).key == "clock"


def test_peeking_does_not_consume_a_slot(app, now):
    app.carousel.min_advance_interval = 0
    first = app.carousel.select("main", app.context(now), advance=True).key
    for _ in range(5):
        assert app.carousel.select("main", app.context(now), advance=False).key == first
    assert app.carousel.select("main", app.context(now), advance=True).key != first


def test_a_rapid_second_fetch_does_not_burn_a_slot(app, now):
    """Guards against a device retry skipping a scene nobody ever saw."""
    app.carousel.min_advance_interval = 60
    a = app.carousel.select("main", app.context(now)).key
    assert app.carousel.select("main", app.context(now)).key == a


def test_when_conditions_gate_entries(app):
    ctx_day = app.context(datetime(2026, 9, 8, 12, 0, tzinfo=TZ))
    ctx_night = app.context(datetime(2026, 9, 8, 21, 0, tzinfo=TZ))
    assert [s.key for s in app.carousel.candidates("gated", ctx_day)] == ["blank"]
    assert [s.key for s in app.carousel.candidates("gated", ctx_night)] == ["clock", "blank"]


def test_rotation_survives_a_restart(app, project, now):
    app.carousel.min_advance_interval = 0
    app.carousel.select("main", app.context(now))
    app.carousel.select("main", app.context(now))

    fresh = Carousel(load_settings(project / "config" / "settings.yaml"))
    fresh.min_advance_interval = 0
    assert fresh.state_for("main")["last_key"] == "clock"
    assert fresh.select("main", app.context(now)).key == "todos(count=3)"


def test_reordering_the_channel_does_not_make_the_sequence_jump(app, project, now):
    """Rotation tracks the scene key, not a positional index."""
    import yaml

    app.carousel.min_advance_interval = 0
    assert app.carousel.select("main", app.context(now)).key == "todos(count=3)"

    cfg_path = project / "config" / "settings.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["channels"]["main"] = [
        {"scene": "clock"},
        {"scene": "holiday", "takeover": True},
        {"scene": "todos", "params": {"count": 3}},
    ]
    cfg_path.write_text(yaml.safe_dump(cfg))

    fresh = Carousel(load_settings(cfg_path))
    fresh.min_advance_interval = 0
    # Last shown was todos; the next one after it is still clock, not "index 1".
    assert fresh.select("main", app.context(now)).key == "clock"


def test_reset_returns_to_the_first_available_scene(app, now):
    app.carousel.min_advance_interval = 0
    app.carousel.select("main", app.context(now))
    app.carousel.select("main", app.context(now))
    app.carousel.reset("main")
    assert app.carousel.select("main", app.context(now)).key == "todos(count=3)"


def test_clock_mode_is_a_pure_function_of_time(app, now):
    app.settings.carousel_mode = "clock"
    app.settings.carousel_dwell = 300
    picks = {app.carousel.select("main", app.context(now)).key for _ in range(5)}
    assert len(picks) == 1, "clock mode must not drift within one dwell window"


def test_an_unknown_channel_selects_nothing(app, now):
    assert app.carousel.select("nope", app.context(now)) is None


def test_a_scene_that_raises_during_availability_is_skipped_not_fatal(app, now, monkeypatch):
    from glance.scenes import REGISTRY

    def boom(ctx, params):
        raise RuntimeError("source exploded")

    monkeypatch.setattr(REGISTRY["todos"], "available_fn", boom)
    assert [s.key for s in app.carousel.candidates("main", app.context(now))] == ["clock"]
