"""Time-of-day dimming."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from glance.brightness import Brightness, apply
from glance.canvas import Canvas

TZ = ZoneInfo("America/Los_Angeles")


def at(hour, minute=0):
    return datetime(2026, 9, 11, hour, minute, tzinfo=TZ)


def test_daytime_is_full_brightness():
    b = Brightness.from_config({})
    for hour in (9, 12, 15, 18, 20):
        assert b.level_at(at(hour)) == pytest.approx(1.0), hour


def test_night_is_dim():
    b = Brightness.from_config({})
    assert b.level_at(at(23, 30)) < 0.3
    assert b.level_at(at(3)) < 0.3


def test_it_ramps_rather_than_jumps():
    """A step would be visible as a flicker while you are looking at it."""
    b = Brightness.from_config({})
    levels = [b.level_at(at(20, m)) for m in (0, 30, 59)]
    assert levels[0] > levels[1] > levels[2]


def test_the_ramp_wraps_through_midnight():
    b = Brightness.from_config({})
    before, after = b.level_at(at(23, 59)), b.level_at(at(0, 1))
    assert abs(before - after) < 0.05, "no discontinuity at midnight"


def test_a_floor_stops_the_panel_going_black():
    b = Brightness.from_config({"schedule": [("00:00", 0.0)], "floor": 0.1})
    assert b.level_at(at(3)) == pytest.approx(0.1)


def test_it_can_be_switched_off():
    assert Brightness.from_config(False).level_at(at(3)) == 1.0


def test_a_plain_number_pins_the_level():
    b = Brightness.from_config(0.4)
    assert b.level_at(at(3)) == b.level_at(at(13)) == pytest.approx(0.4)


def test_a_custom_schedule_is_honoured():
    b = Brightness.from_config({"schedule": [
        {"at": "08:00", "level": 1.0},
        {"at": "18:00", "level": 0.2},
    ]})
    assert b.level_at(at(8)) == pytest.approx(1.0)
    assert b.level_at(at(18)) == pytest.approx(0.2)


# --- applying it ------------------------------------------------------------

def test_applying_dims_the_pixels():
    c = Canvas(64)
    c.fill_rect(0, 0, 64, 32, (200, 200, 200))
    apply(c, 0.5)
    assert c.image.getpixel((0, 0)) == (100, 100, 100)


def test_a_lit_pixel_never_goes_fully_dark():
    """Rounding a dim colour to black would punch holes in the artwork."""
    c = Canvas(64)
    c.fill_rect(0, 0, 10, 10, (20, 20, 20))
    apply(c, 0.02)
    r, g, b = c.image.getpixel((0, 0))
    assert (r, g, b) != (0, 0, 0)


def test_black_stays_black():
    c = Canvas(64)
    c.clear("black")
    apply(c, 0.5)
    assert c.image.getpixel((0, 0)) == (0, 0, 0)


def test_full_brightness_changes_nothing():
    c = Canvas(64)
    c.fill_rect(0, 0, 64, 32, (123, 45, 200))
    before = list(c.image.get_flattened_data())
    apply(c, 1.0)
    assert list(c.image.get_flattened_data()) == before


def test_a_channel_that_was_zero_stays_zero():
    """Dimming must not tint a pure colour."""
    c = Canvas(64)
    c.fill_rect(0, 0, 8, 8, (255, 0, 0))
    apply(c, 0.3)
    r, g, b = c.image.getpixel((0, 0))
    assert g == 0 and b == 0 and 0 < r < 255


# --- end to end -------------------------------------------------------------

def test_rendering_at_night_is_dimmer_than_at_noon(app):
    noon, _ = app.render_scene("date", {}, app.context(at(12)))
    night, _ = app.render_scene("date", {}, app.context(at(23, 30)))
    brightest = lambda c: max(sum(p) for p in c.image.get_flattened_data())
    assert brightest(night) < brightest(noon)


def test_the_override_pins_it_for_previewing(app):
    a, _ = app.render_scene("date", {}, app.context(at(3), brightness=1.0))
    b, _ = app.render_scene("date", {}, app.context(at(12), brightness=1.0))
    assert list(a.image.get_flattened_data()) == list(b.image.get_flattened_data())


def test_animated_scenes_are_dimmed_frame_by_frame(app):
    fr, _ = app.render_scene("pulse", {"mode": "pulse"}, app.context(at(23, 30)))
    for canvas in fr.canvases:
        assert max(sum(p) for p in canvas.image.get_flattened_data()) < 700
