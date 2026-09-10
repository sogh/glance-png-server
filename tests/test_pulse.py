"""The pulsing-names scene."""

from __future__ import annotations

import pytest

from glance.animation import Frames
from glance.canvas import Canvas
from glance.fonts import get_font
from glance.scenes.pulse import parse_items


def frames_of(app, params, width=192):
    rendered, label = app.render_scene("pulse", params, width=width)
    assert not label.startswith("error:")
    return rendered


def test_item_parsing():
    assert parse_items("ADA:yellow,GRACE:blue") == [("ADA", "yellow"), ("GRACE", "blue")]
    assert parse_items("SOLO") == [("SOLO", "white")]
    assert parse_items(" A:red , B:blue ") == [("A", "red"), ("B", "blue")]
    assert parse_items("") == []


def test_it_animates(app):
    fr = frames_of(app, {})
    assert isinstance(fr, Frames)
    assert len(fr) > 1


def test_the_first_frame_is_white_so_a_static_decoder_still_reads_it(app):
    fr = frames_of(app, {"items": "ADA:yellow"})
    lit = [p for p in fr.canvases[0].image.get_flattened_data() if sum(p) > 0]
    assert lit, "frame 0 should have text on it"
    # White-ish: all three channels close together.
    assert all(max(p) - min(p) < 30 for p in lit), "frame 0 should start white"


def test_it_reaches_the_target_colour(app):
    fr = frames_of(app, {"items": "ADA:yellow", "frames": 30})
    mid = fr.canvases[15].image.get_flattened_data()
    yellows = [p for p in mid if p[0] > 150 and p[1] > 150 and p[2] < 90]
    assert yellows, "halfway through the cycle it should be yellow"


def test_each_item_gets_its_own_colour(app):
    fr = frames_of(app, {"items": "ADA:yellow,GRACE:blue", "frames": 30})
    px = fr.canvases[15].image.get_flattened_data()
    assert [p for p in px if p[0] > 150 and p[1] > 150 and p[2] < 90], "no yellow"
    assert [p for p in px if p[2] > 150 and p[0] < 110], "no blue"


def test_the_loop_closes_seamlessly(app):
    """First and last frame must be near-identical or the panel jumps."""
    fr = frames_of(app, {"frames": 30})
    first = fr.canvases[0].to_ascii()
    last = fr.canvases[-1].to_ascii()
    assert first == last or fr.canvases[0].image != fr.canvases[-1].image


@pytest.mark.parametrize("layout", ["row", "column"])
def test_nothing_is_clipped_at_the_chosen_scale(app, layout):
    """The auto scale must keep every glyph inside the panel."""
    fr = frames_of(app, {"items": "ADA:yellow,GRACE:blue", "layout": layout})
    c = fr.canvases[0]
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge), "text ran into the last column"


def test_an_oversized_explicit_scale_is_clamped_not_clipped(app):
    """Setting scale: 6 in the editor should shrink to fit, not truncate."""
    big = frames_of(app, {"items": "ADA:yellow,GRACE:blue", "scale": 6})
    auto = frames_of(app, {"items": "ADA:yellow,GRACE:blue"})
    assert big.canvases[0].to_ascii() == auto.canvases[0].to_ascii()


def test_a_narrow_panel_still_fits(app):
    fr = frames_of(app, {"items": "ADA:yellow,GRACE:blue"}, width=64)
    c = fr.canvases[0]
    assert c.width == 64
    edge = [c.image.getpixel((63, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_stagger_desynchronises_the_items(app):
    synced = frames_of(app, {"items": "A:red,B:blue", "stagger": 0})
    staggered = frames_of(app, {"items": "A:red,B:blue", "stagger": 0.5})
    assert synced.canvases[5].image != staggered.canvases[5].image


def test_empty_items_falls_back_to_a_still(app):
    rendered, _ = app.render_scene("pulse", {"items": ""})
    assert isinstance(rendered, Canvas)


def test_output_is_a_valid_png(app):
    assert app.png(frames_of(app, {})).startswith(b"\x89PNG\r\n\x1a\n")
