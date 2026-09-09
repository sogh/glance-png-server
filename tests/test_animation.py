"""Animated output.

Whether the panel honours APNG is unknown -- the value of these tests is that
the bytes we emit stay a *valid single-frame PNG* to any decoder that does
not, so trying costs nothing.
"""

from __future__ import annotations

import io
import struct
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from glance.animation import Frames, marquee_frames
from glance.canvas import Canvas
from glance.scenes import REGISTRY

TZ = ZoneInfo("America/Los_Angeles")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk_names(data: bytes) -> list[str]:
    names, i = [], 8
    while i < len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        names.append(data[i + 4:i + 8].decode("ascii", "replace"))
        i += 12 + length
    return names


def test_marquee_produces_multiple_frames():
    frames = marquee_frames(192, "SCROLLING TEXT")
    assert len(frames) > 1
    assert frames.width == 192 and frames.height == 32


def test_output_is_a_valid_png_to_any_decoder():
    """The whole premise: an APNG is a PNG. A device that ignores the
    animation chunks must still get a normal image."""
    data = marquee_frames(192, "HELLO").to_png()
    assert data.startswith(PNG_SIGNATURE)
    names = chunk_names(data)
    assert names[0] == "IHDR" and names[-1] == "IEND"
    assert "IDAT" in names, "frame 0 must live in a plain IDAT"

    img = Image.open(io.BytesIO(data))
    assert img.size == (192, 32)


def test_output_carries_the_animation_chunks():
    names = chunk_names(marquee_frames(192, "HELLO").to_png())
    assert "acTL" in names          # animation control
    assert "fcTL" in names          # per-frame control
    assert "fdAT" in names          # subsequent frame data


def test_animations_stay_far_below_the_response_cap():
    long_text = "Merry Christmas from the whole house and everyone in it"
    for text in ("HI", long_text):
        assert len(marquee_frames(192, text).to_png()) < 200_000


def test_frame_count_is_bounded_for_very_long_text():
    frames = marquee_frames(192, "x" * 4000, max_frames=60)
    assert len(frames) <= 60


def test_a_single_frame_encodes_as_an_ordinary_png():
    c = Canvas(192)
    c.centered("STILL", "white")
    data = Frames(canvases=[c]).to_png()
    assert "acTL" not in chunk_names(data)


def test_frames_rejects_mismatched_sizes():
    with pytest.raises(ValueError):
        Frames(canvases=[Canvas(192), Canvas(64)])


def test_frames_rejects_being_empty():
    with pytest.raises(ValueError):
        Frames(canvases=[])


def test_first_returns_what_a_static_decoder_shows():
    frames = marquee_frames(192, "ABC")
    assert frames.first() is frames.canvases[0]


def test_marquee_scene_renders_frames(app, now):
    rendered, label = app.render_scene("marquee", {"text": "SHIP IT"}, app.context(now))
    assert isinstance(rendered, Frames)
    assert not label.startswith("error:")
    assert app.png(rendered).startswith(PNG_SIGNATURE)


def test_marquee_scene_without_text_falls_back_to_a_still(app, now):
    rendered, _ = app.render_scene("marquee", {}, app.context(now))
    assert isinstance(rendered, Canvas)


def test_marquee_scene_is_always_available(app, now):
    assert REGISTRY["marquee"].available(app.context(now), {})


# --- clock lead ------------------------------------------------------------

def test_clock_lead_shifts_the_displayed_time(app):
    """The device redraws a cached frame until its next fetch, so a clock is
    only correct at the instant it is rendered. `lead` centres that error."""
    ctx = app.context(datetime(2026, 9, 8, 14, 0, tzinfo=TZ))
    plain, _ = app.render_scene("clock", {}, ctx)
    led, _ = app.render_scene("clock", {"lead": 150}, ctx)
    assert plain.to_ascii() != led.to_ascii()


def test_clock_lead_of_zero_changes_nothing(app):
    ctx = app.context(datetime(2026, 9, 8, 14, 0, tzinfo=TZ))
    a, _ = app.render_scene("clock", {}, ctx)
    b, _ = app.render_scene("clock", {"lead": 0}, ctx)
    assert a.to_ascii() == b.to_ascii()


def test_clock_lead_can_roll_the_date_forward(app):
    ctx = app.context(datetime(2026, 9, 8, 23, 58, tzinfo=TZ))
    rolled, _ = app.render_scene("clock", {"lead": 300}, ctx)
    assert "error" not in rolled.to_ascii()
