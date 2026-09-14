"""The gradient-names scene.

Written as an animation first. The device renders frame zero of an APNG and
stops, so the colour transition moved from across time to across the letters,
and the animation was removed entirely.
"""

from __future__ import annotations

import pytest

from glance.canvas import Canvas
from glance.scenes.pulse import parse_items


def render(app, params, width=192):
    canvas, label = app.render_scene("pulse", params, width=width)
    assert not label.startswith("error:")
    return canvas


def test_item_parsing():
    assert parse_items("ADA:yellow,GRACE:blue") == [("ADA", "yellow"), ("GRACE", "blue")]
    assert parse_items("SOLO") == [("SOLO", "white")]
    assert parse_items(" A:red , B:blue ") == [("A", "red"), ("B", "blue")]
    assert parse_items("") == []


def test_it_is_a_single_still(app):
    assert isinstance(render(app, {}), Canvas)


def test_the_gradient_ramps_across_the_letters(app):
    c = render(app, {"items": "ADA:yellow"})
    px = [(x, c.image.getpixel((x, y)))
          for x in range(c.width) for y in range(32)
          if sum(c.image.getpixel((x, y))) > 0]
    assert px
    first_x, last_x = px[0][0], px[-1][0]
    left = [p for x, p in px if x < first_x + 6]
    right = [p for x, p in px if x > last_x - 6]
    # White has a high blue channel; yellow has almost none.
    assert sum(p[2] for p in left) / len(left) > 150, "should start near white"
    assert sum(p[2] for p in right) / len(right) < 90, "should end at the colour"


def test_each_item_ramps_to_its_own_colour(app):
    px = render(app, {"items": "ADA:yellow,GRACE:blue"}).image.get_flattened_data()
    assert [p for p in px if p[0] > 150 and p[1] > 150 and p[2] < 90], "no yellow end"
    assert [p for p in px if p[2] > 150 and p[0] < 110], "no blue end"


def test_the_start_colour_is_configurable(app):
    default = render(app, {"items": "ABCDE:blue"})
    grey = render(app, {"items": "ABCDE:blue", "from": "dim"})
    lit = lambda c: {i for i, p in enumerate(c.image.get_flattened_data()) if sum(p) > 0}
    assert lit(default) == lit(grey), "the same pixels should be lit"
    assert (list(default.image.get_flattened_data())
            != list(grey.image.get_flattened_data())), "but in different colours"


@pytest.mark.parametrize("layout", ["row", "column"])
def test_nothing_is_clipped_at_the_chosen_scale(app, layout):
    c = render(app, {"items": "ADA:yellow,GRACE:blue", "layout": layout})
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge), "text ran into the last column"


def test_an_oversized_explicit_scale_is_clamped_not_clipped(app):
    """Setting scale: 6 in the editor should shrink to fit, not truncate."""
    big = render(app, {"items": "ADA:yellow,GRACE:blue", "scale": 6})
    auto = render(app, {"items": "ADA:yellow,GRACE:blue"})
    assert big.to_ascii() == auto.to_ascii()


def test_a_narrow_panel_still_fits(app):
    c = render(app, {"items": "ADA:yellow,GRACE:blue"}, width=64)
    assert c.width == 64
    assert all(sum(c.image.getpixel((63, y))) == 0 for y in range(32))


def test_a_one_character_item_does_not_divide_by_zero(app):
    c = render(app, {"items": "X:red"})
    assert [p for p in c.image.get_flattened_data() if sum(p) > 0]


def test_empty_items_still_draws_something(app):
    c = render(app, {"items": ""})
    assert isinstance(c, Canvas)
    assert [p for p in c.image.get_flattened_data() if sum(p) > 0]


def test_output_is_a_valid_png(app):
    assert app.png(render(app, {})).startswith(b"\x89PNG\r\n\x1a\n")


def test_canvas_text_gradient_directly():
    c = Canvas(192)
    width = c.text_gradient(2, 12, "HELLO", "white", "red")
    assert width > 0
    lit = [p for p in c.image.get_flattened_data() if sum(p) > 0]
    assert lit
    assert any(p[2] > 150 for p in lit), "white end present"
    assert any(p[0] > 150 and p[2] < 90 for p in lit), "red end present"
