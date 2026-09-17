from __future__ import annotations

import pytest

from glance.canvas import Canvas
from glance.fonts import FONT_3X5, FONT_5X7, FONT_5X7_MONO, FONTS
from glance.palette import PWM_FLOOR, dim, parse, snap


@pytest.mark.parametrize("font", list(FONTS.values()), ids=lambda f: f.name)
def test_every_glyph_is_a_well_formed_grid(font):
    for ch, art in font.source.items():
        rows = art.split("/")
        assert len(rows) == font.height, f"{font.name}:{ch!r} row count"
        assert all(len(r) == font.cell_width for r in rows), f"{font.name}:{ch!r} row width"
        assert set("".join(rows)) <= {"#", "."}, f"{font.name}:{ch!r} bad characters"


def test_five_by_seven_covers_printable_ascii():
    missing = [chr(c) for c in range(32, 127) if chr(c) not in FONT_5X7.source]
    assert not missing


def test_proportional_is_narrower_than_mono():
    text = "Illinois 111"
    assert FONT_5X7.measure(text) < FONT_5X7_MONO.measure(text)


def test_mono_advance_is_uniform():
    assert len({FONT_5X7_MONO.advance(c) for c in "1MW.i"}) == 1


def test_measure_matches_rendered_mask_width():
    for text in ("Hello", "1:45pm", "W", "", "iiiii"):
        assert FONT_5X7.mask(text).width == max(FONT_5X7.measure(text), 1)


def test_unknown_characters_fall_back_rather_than_crash():
    assert FONT_5X7.measure("café ☃") > 0


def test_truncate_fits_budget_and_marks_the_cut():
    text = "Pick up the dry cleaning before six"
    out = FONT_5X7.truncate(text, 60)
    assert FONT_5X7.measure(out) <= 60
    assert out.endswith("…")
    assert FONT_5X7.truncate("short", 500) == "short"


def test_truncate_returns_empty_when_even_the_marker_will_not_fit():
    assert FONT_5X7.truncate("anything", 1) == ""


def test_wrap_never_exceeds_the_line_width():
    lines = FONT_5X7.wrap("The quick brown fox jumps over the lazy dog", 60)
    assert len(lines) > 1
    assert all(FONT_5X7.measure(line) <= 60 for line in lines)


def test_wrap_hard_splits_a_word_longer_than_the_line():
    lines = FONT_5X7.wrap("Supercalifragilisticexpialidocious", 40)
    assert all(FONT_5X7.measure(line) <= 40 for line in lines)
    assert "".join(lines) == "Supercalifragilisticexpialidocious"


def test_three_by_five_folds_lowercase_to_uppercase():
    assert FONT_3X5.measure("abc") == FONT_3X5.measure("ABC")


def test_panel_height_is_fixed():
    with pytest.raises(ValueError):
        Canvas(width=192, height=16)


def test_panel_width_is_bounded():
    with pytest.raises(ValueError):
        Canvas(width=512)
    with pytest.raises(ValueError):
        Canvas(width=0)


def test_png_round_trips_at_panel_size():
    from io import BytesIO

    from PIL import Image

    c = Canvas(192)
    c.centered("Merry Christmas", "green")
    img = Image.open(BytesIO(c.to_png()))
    assert img.size == (192, 32)


def test_png_stays_far_below_the_one_megabyte_cap():
    c = Canvas(384)
    for x in range(384):
        for y in range(32):
            c.pixel(x, y, (x % 255, y * 8 % 255, (x + y) % 255))
    assert len(c.to_png()) < 1_000_000


def test_scaled_text_is_an_integer_multiple():
    c = Canvas(192)
    single = c.text(0, 0, "88", "white", "5x7mono", scale=1)
    c.clear()
    double = c.text(0, 0, "88", "white", "5x7mono", scale=2)
    assert double == single * 2


def test_drawing_off_canvas_is_clipped_not_fatal():
    c = Canvas(64)
    c.fill_rect(-20, -20, 200, 200, "red")
    c.pixel(999, 999, "red")
    c.text(-50, 28, "overflowing text", "white")
    assert c.image.size == (64, 32)


def test_snap_kills_unstable_low_pwm_values():
    assert snap((PWM_FLOOR - 1, 200, 0)) == (0, 200, 0)
    assert snap((PWM_FLOOR, 0, 0)) == (PWM_FLOOR, 0, 0)


def test_parse_accepts_names_hex_and_tuples():
    assert parse("red") == parse("#FF281E") == (255, 40, 30)
    assert parse("#0f0") == (0, 255, 0)
    assert parse((10, 20, 30)) == (10, 20, 30)
    with pytest.raises(ValueError):
        parse("not-a-color")


def test_dim_reduces_brightness_and_bottoms_out_at_black():
    assert dim("white", 0.5) < parse("white")
    assert dim("white", 0.0) == (0, 0, 0)


def test_fit_downscales_oversized_art_without_distorting_it():
    from PIL import Image

    c = Canvas(192)
    c.fit(Image.new("RGB", (960, 160), (255, 0, 0)))
    # 6:1 source into a 6:1 slot -- should fill the full width.
    assert c.image.getpixel((0, 16)) == (255, 0, 0)
    assert c.image.getpixel((191, 16)) == (255, 0, 0)


@pytest.mark.parametrize("font", [FONT_5X7, FONT_3X5], ids=["5x7", "3x5"])
def test_fonts_cover_what_the_scenes_actually_draw(font):
    """A missing glyph does not fail loudly, it renders '?' -- which is how
    "13%" reached the panel as "13?"."""
    used = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ %@&°.:,;-/'\"!?()+*=<>[]_#$"
    missing = [c for c in used if c not in font.source]
    assert not missing, f"{font.name} cannot draw {missing}"


def test_the_percent_sign_is_not_a_question_mark():
    assert FONT_3X5.mask("%").getbbox() != FONT_3X5.mask("?").getbbox() or \
        FONT_3X5.measure("%") > 0
    assert "%" in FONT_3X5.source


# --- what the device has to decode ------------------------------------------

def png_facts(data: bytes):
    """(bit depth, colour type, inflated scanline bytes) straight from the file."""
    import struct
    import zlib

    width, height, depth, ctype = struct.unpack(">IIBB", data[16:26])
    offset, idat = 8, b""
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        if data[offset + 4:offset + 8] == b"IDAT":
            idat += data[offset + 8:offset + 8 + length]
        offset += 12 + length
    return depth, ctype, len(zlib.decompress(idat))


PALETTE, TRUECOLOUR = 3, 2


def test_a_busy_panel_is_still_palette_encoded():
    """`getcolors(256)` returns None when there are MORE than 256 colours, and
    reading that as "cannot quantize" emitted 24-bit truecolour for exactly the
    images that most needed reducing. A crest panel has ~800 colours and was
    three times the inflated size of anything else on the strip."""
    from glance.canvas import Canvas

    busy = Canvas(width=192)
    for x in range(192):                       # ~6000 distinct colours
        for y in range(32):
            busy.pixel(x, y, (x % 256, (y * 8) % 256, (x * y) % 256))
    assert busy.image.getcolors(maxcolors=256) is None, "fixture is not busy enough"

    depth, ctype, inflated = png_facts(busy.to_png(quantize=True))
    assert ctype == PALETTE, "fell back to truecolour"
    assert depth <= 8
    assert inflated <= 192 * 32 + 32, inflated       # one byte per pixel, plus filters


def test_quantising_leaves_a_simple_panel_alone():
    from glance.canvas import Canvas

    plain = Canvas(width=192)
    plain.clear("black")
    plain.text(4, 12, "HELLO", "amber", "5x7")
    depth, ctype, _ = png_facts(plain.to_png(quantize=True))
    assert ctype == PALETTE
    assert depth <= 4, "a handful of colours should not need 8 bits"


def test_every_registered_scene_decodes_small(app, now):
    """The device has to hold this. Nothing should need more than one byte per
    pixel of scanline data."""
    from glance.scenes import REGISTRY

    budget = 192 * 32 + 64
    for scene_id in sorted(REGISTRY):
        if scene_id == "static":
            continue
        canvas, _ = app.render_scene(scene_id, {}, app.context(now))
        depth, ctype, inflated = png_facts(app.png(canvas))
        assert ctype == PALETTE, f"{scene_id} is truecolour"
        assert inflated <= budget, f"{scene_id} inflates to {inflated}b"
