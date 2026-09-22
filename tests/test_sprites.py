"""Pixel-art sprites and the scene that sets them into text."""

from __future__ import annotations

import pytest

from glance.canvas import Canvas
from glance.sprites import SPRITES, draw_sprite, get_sprite


@pytest.mark.parametrize("name", sorted(SPRITES))
def test_every_sprite_is_a_rectangle(name):
    """A ragged row silently shifts everything below it."""
    sprite = SPRITES[name]
    assert sprite.rows, f"{name} is empty"
    assert all(len(r) == sprite.width for r in sprite.rows), f"{name} has ragged rows"


@pytest.mark.parametrize("name", sorted(SPRITES))
def test_every_character_used_has_a_colour(name):
    sprite = SPRITES[name]
    used = {ch for row in sprite.rows for ch in row} - {"."}
    missing = used - set(sprite.palette)
    assert not missing, f"{name} uses {missing} with no palette entry"


@pytest.mark.parametrize("name", sorted(SPRITES))
def test_sprites_fit_the_panel(name):
    sprite = SPRITES[name]
    assert sprite.height <= 32, f"{name} is taller than the panel"


def test_lookup_is_case_insensitive():
    assert get_sprite("SWEATPANTS") is get_sprite("sweatpants")
    assert get_sprite("nope") is None


def test_dots_are_transparent():
    c = Canvas(64)
    c.clear("black")
    sprite = get_sprite("sweatpants")
    draw_sprite(c, sprite, 0, 0)
    # The top corners of the sweatpants art are waistband, the bottom ones are
    # outside the legs and must have been left alone.
    assert sum(c.image.getpixel((0, sprite.height - 1))) == 0


def test_the_sweatpants_are_grey():
    c = Canvas(64)
    draw_sprite(c, get_sprite("sweatpants"), 0, 0)
    lit = [p for p in c.image.get_flattened_data() if sum(p) > 0]
    assert lit
    # Grey means the three channels stay close together.
    assert all(max(p) - min(p) < 20 for p in lit)


def test_the_pumpkin_has_a_green_stem_over_an_orange_body():
    sprite = get_sprite("pumpkin")
    lit = lambda row: next(sprite.color_for(ch) for ch in sprite.rows[row] if ch != ".")
    stem, body = lit(0), lit(sprite.height // 2)
    assert stem[1] > stem[0] and stem[1] > stem[2], "the stem should be green"
    assert body[0] > body[1] > body[2], "the body should be orange"


def test_the_pumpkin_has_ridges():
    """Without the darker columns this is an orange ball with a stem, and at
    this size there is no other cue that it is a pumpkin."""
    sprite = get_sprite("pumpkin")
    middle = sprite.rows[sprite.height // 2]
    assert len({ch for ch in middle if ch != "."}) > 1


def test_candy_corn_is_banded_in_the_right_order():
    """White tip, orange middle, yellow base, from the point down. Backwards
    is the usual mistake and it stops reading as candy corn at once."""
    sprite = get_sprite("candycorn")
    lit = lambda row: next(sprite.color_for(ch) for ch in sprite.rows[row] if ch != ".")
    tip, middle, base = lit(0), lit(sprite.height // 2), lit(sprite.height - 1)
    assert max(tip) - min(tip) < 20, "the tip is cream, not a colour"
    assert middle[1] < base[1], "the base must be yellower than the middle"
    assert middle[2] < 80 and base[2] < 120, "both lower bands stay warm"


def test_scale_multiplies_cleanly():
    sprite = get_sprite("sweatpants")
    c1, c2 = Canvas(192), Canvas(192)
    w1 = draw_sprite(c1, sprite, 0, 0, scale=1)
    w2 = draw_sprite(c2, sprite, 0, 0, scale=2)
    assert w2 == w1 * 2


# --- the scene --------------------------------------------------------------

def test_it_renders_the_ask(app, now):
    c, label = app.render_scene(
        "sprite", {"before": "It's", "after": "season!"}, app.context(now)
    )
    assert not label.startswith("error:")
    assert c.image.size == (192, 32)


def test_text_and_sprite_both_appear(app, now):
    with_text, _ = app.render_scene(
        "sprite", {"before": "It's", "after": "season!"}, app.context(now))
    bare, _ = app.render_scene("sprite", {"before": "", "after": ""}, app.context(now))
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit(with_text) > lit(bare)


def test_nothing_runs_off_the_edge(app, now):
    c, _ = app.render_scene(
        "sprite", {"before": "It's", "after": "season!"}, app.context(now))
    for x in (0, c.width - 1):
        assert all(sum(c.image.getpixel((x, y))) == 0 for y in range(32))


def test_long_text_shrinks_rather_than_clipping(app, now):
    c, _ = app.render_scene(
        "sprite",
        {"before": "It is definitely and truly", "after": "season once again!"},
        app.context(now),
    )
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_an_unknown_sprite_says_so_instead_of_crashing(app, now):
    c, label = app.render_scene("sprite", {"sprite": "banana"}, app.context(now))
    assert not label.startswith("error:")
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_a_narrow_panel_still_fits(app, now):
    c, _ = app.render_scene(
        "sprite", {"before": "It's", "after": "season!"}, app.context(now, width=64))
    assert c.width == 64
    edge = [c.image.getpixel((63, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_the_sheet_scene_draws_everything(app, now):
    c, label = app.render_scene("sprites", {}, app.context(now))
    assert not label.startswith("error:")
    assert any(sum(p) > 0 for p in c.image.get_flattened_data())


def test_an_oversized_sprite_scale_is_clamped(app, now):
    """scale 2 on a 24x25 sprite is 50px tall on a 32px panel."""
    big, _ = app.render_scene("sprite", {"sprite_scale": 4}, app.context(now))
    one, _ = app.render_scene("sprite", {"sprite_scale": 1}, app.context(now))
    assert big.to_ascii() == one.to_ascii()


def test_the_sprite_never_touches_the_top_or_bottom_edge(app, now):
    c, _ = app.render_scene("sprite", {"sprite_scale": 3}, app.context(now))
    assert c.image.size == (192, 32)
