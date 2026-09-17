"""Vocabulary decks, accented glyphs, and the language panel."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from glance.fonts import get_font, to_ascii
from glance.scenes import REGISTRY
from glance.sources.vocabulary import Deck, Entry, Vocabulary, parse_deck

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 9, 14, 12, 0, tzinfo=TZ)
SHIPPED = Path("config/vocabulary")


# --- the font ---------------------------------------------------------------

def test_the_5x7_font_has_every_accent_spanish_and_french_need():
    font = get_font("5x7")
    for ch in "áéíóúüñ¿¡àâçèêëîïôùûÿœ":
        assert ch in font.source, ch
        assert ch.upper() in font.source, ch.upper()


def test_an_accented_letter_is_seven_rows_like_everything_else():
    font = get_font("5x7")
    for ch in "áÉñÑçÇ¿¡œŒ":
        assert len(font.source[ch].split("/")) == 7, ch
        assert font.glyph(ch).width > 0, ch


def test_accents_are_not_folded_away_by_a_font_that_has_them():
    """"año" is the year and "ano" is not. A panel that quietly renders the
    second one is worse than no panel."""
    font = get_font("5x7")
    assert to_ascii("el año", font.source) == "el año"
    assert to_ascii("¿Cómo estás?", font.source) == "¿Cómo estás?"
    assert to_ascii("français", font.source) == "français"


def test_a_font_without_them_still_folds_rather_than_drawing_question_marks():
    """The 3x5 is uppercase-only with no room above a letter for a mark, so
    there it is still better to fold than to print "A?O"."""
    font = get_font("3x5")
    assert to_ascii("el año", font.source) == "el ano"
    assert to_ascii("Renée", font.source) == "Renee"


def test_accented_letters_are_wider_than_nothing_and_measurable():
    font = get_font("5x7")
    assert font.measure("año") > font.measure("ao")
    assert font.measure("ñ") == font.measure("n")


def test_the_inverted_marks_are_the_upright_ones_turned_over():
    font = get_font("5x7")
    rows = lambda ch: font.source[ch].split("/")
    flipped = ["".join(reversed(r)) for r in reversed(rows("?"))]
    assert rows("¿") == flipped


def test_the_cedilla_keeps_the_whole_letter():
    """Slicing rows off the bottom of a c to make room left a c with no curve,
    which reads as "c." with a speck under it."""
    font = get_font("5x7")
    body = font.source["ç"].split("/")[1:6]
    assert body == font.source["c"].split("/")[2:7]


# --- parsing ----------------------------------------------------------------

def test_the_short_form_is_a_plain_string():
    deck = parse_deck("es", ["el año = the year"])
    assert deck.entries == [Entry(term="el año", gloss="the year")]


def test_the_short_form_also_survives_being_written_as_a_mapping():
    """`- term: hola = hello` reads as one string to yaml, not as two fields.
    Accepting it beats silently dropping the entry."""
    deck = parse_deck("es", [{"term": "hola = hello"}])
    assert deck.entries == [Entry(term="hola", gloss="hello")]


def test_the_long_form_carries_a_note():
    deck = parse_deck("es", [{"term": "buenos días", "gloss": "good morning",
                              "note": "BWEH-nos", "tags": ["greeting"]}])
    assert deck.entries[0].note == "BWEH-nos"
    assert deck.entries[0].tags == ["greeting"]


def test_an_entry_with_no_meaning_is_dropped_not_drawn_blank():
    assert parse_deck("es", ["hola", {"term": "x"}, ""]).entries == []


def test_a_deck_can_name_itself():
    deck = parse_deck("es", {"label": "ESPANOL", "words": ["hola = hello"]})
    assert deck.label == "ESPANOL"
    assert len(deck) == 1


def test_the_article_is_separated_from_the_noun():
    assert Entry("la granja", "the farm").article == "la"
    assert Entry("la granja", "the farm").rest == "granja"
    assert Entry("hola", "hello").article == ""
    assert Entry("hola", "hello").rest == "hola"
    # "la" is feminine in both languages, which is the point of sharing a set.
    assert Entry("la ferme", "the farm").article == "la"


# --- choosing what to show --------------------------------------------------

def deck_of(n=10):
    return parse_deck("es", [f"palabra{i} = word{i}" for i in range(n)])


def test_the_entry_is_a_pure_function_of_the_clock():
    """No stored state: it survives a restart, never double-advances on a
    device retry, and two panels pointed at it agree."""
    deck = deck_of()
    assert deck.at(NOW, 900) is deck.at(NOW, 900)
    assert deck.at(NOW, 900) is deck.at(NOW + timedelta(seconds=30), 900)


def test_it_moves_on_at_the_rotate_interval():
    deck = deck_of()
    seen = {deck.at(NOW + timedelta(seconds=900 * i), 900).term for i in range(10)}
    assert len(seen) == 10


def test_a_shuffle_is_stable_within_a_day_and_changes_between_days():
    """A new order every render would show three words a minute and teach
    none of them; a fixed order shows the same word at the same time daily."""
    deck = deck_of(30)
    morning = deck.order(NOW, shuffled=True)
    evening = deck.order(NOW + timedelta(hours=9), shuffled=True)
    tomorrow = deck.order(NOW + timedelta(days=1), shuffled=True)
    assert [e.term for e in morning] == [e.term for e in evening]
    assert [e.term for e in morning] != [e.term for e in tomorrow]
    assert sorted(e.term for e in tomorrow) == sorted(e.term for e in morning)


def test_unshuffled_runs_the_file_in_order():
    deck = deck_of()
    assert [e.term for e in deck.order(NOW, shuffled=False)] == \
           [e.term for e in deck.entries]


def test_progress_runs_from_zero_to_one_across_a_slot():
    deck = deck_of()
    start = datetime.fromtimestamp((int(NOW.timestamp()) // 900) * 900, tz=TZ)
    assert deck.progress(start, 900) == pytest.approx(0.0, abs=0.01)
    assert deck.progress(start + timedelta(seconds=450), 900) == pytest.approx(0.5, abs=0.01)


def test_an_empty_deck_has_nothing_to_show_rather_than_raising():
    assert parse_deck("es", []).at(NOW, 900) is None


# --- the directory ----------------------------------------------------------

def test_decks_are_found_by_filename(tmp_path):
    (tmp_path / "es.yaml").write_text("- hola = hello\n", encoding="utf-8")
    (tmp_path / "fr.yml").write_text("- salut = hi\n", encoding="utf-8")
    books = Vocabulary(tmp_path)
    assert books.languages == ["es", "fr"]
    assert books.get("ES") is not None          # case-insensitive


def test_editing_a_deck_reloads_it(tmp_path):
    path = tmp_path / "es.yaml"
    path.write_text("- hola = hello\n", encoding="utf-8")
    books = Vocabulary(tmp_path)
    assert len(books.get("es")) == 1
    import os, time
    path.write_text("- hola = hello\n- adiós = goodbye\n", encoding="utf-8")
    os.utime(path, (time.time() + 2, time.time() + 2))
    assert len(books.get("es")) == 2


def test_a_broken_deck_keeps_the_last_good_one(tmp_path):
    path = tmp_path / "es.yaml"
    path.write_text("- hola = hello\n", encoding="utf-8")
    books = Vocabulary(tmp_path)
    assert len(books.get("es")) == 1
    import os, time
    path.write_text("- [unclosed\n", encoding="utf-8")
    os.utime(path, (time.time() + 2, time.time() + 2))
    assert len(books.get("es")) == 1, "should not lose the working deck"
    assert books.last_error and "es.yaml" in books.last_error


def test_a_missing_directory_is_not_an_error(tmp_path):
    books = Vocabulary(tmp_path / "nope")
    assert books.languages == []
    assert books.get("es") is None


# --- the shipped decks ------------------------------------------------------

@pytest.mark.parametrize("code", ["es", "fr"])
def test_every_shipped_word_can_actually_be_drawn(code):
    """The panel folds silently when a glyph is missing, so a word with an
    accent the font lacks would render as a different word."""
    font = get_font("5x7")
    deck = Vocabulary(SHIPPED).get(code)
    assert deck and len(deck) > 50
    for entry in deck.entries:
        for text in (entry.term, entry.gloss, entry.note):
            assert to_ascii(text, font.source) == text, f"{code}: {text!r}"


@pytest.mark.parametrize("code", ["es", "fr"])
def test_every_shipped_word_fits_the_panel(code):
    font = get_font("5x7")
    small = get_font("3x5")
    deck = Vocabulary(SHIPPED).get(code)
    for entry in deck.entries:
        assert font.measure(entry.term) <= 188, f"{code}: {entry.term!r}"
        assert small.measure(entry.gloss) <= 188, f"{code}: {entry.gloss!r}"


@pytest.mark.parametrize("code", ["es", "fr"])
def test_the_shipped_decks_have_no_duplicates(code):
    deck = Vocabulary(SHIPPED).get(code)
    terms = [e.term.lower() for e in deck.entries]
    assert len(terms) == len(set(terms)), sorted(
        t for t in terms if terms.count(t) > 1)


# --- the scene --------------------------------------------------------------

def ctx_with(app, tmp_path, body="- la granja = the farm\n"):
    (tmp_path / "es.yaml").write_text(body, encoding="utf-8")
    ctx = app.context(NOW, brightness=1.0)
    ctx.vocabulary = Vocabulary(tmp_path)
    return ctx


def test_the_scene_draws_a_word(app, tmp_path):
    ctx = ctx_with(app, tmp_path)
    scene = REGISTRY["language"]
    assert scene.available(ctx, {"language": "es"})
    c = scene.render(ctx, {"language": "es"})
    assert c.image.get_flattened_data().count((0, 0, 0)) < 192 * 32


def test_the_article_is_drawn_in_its_own_colour(app, tmp_path):
    """Gender is the thing beginners get wrong for years, and colouring the
    article puts it on every card for free."""
    ctx = ctx_with(app, tmp_path)
    scene = REGISTRY["language"]
    apart = scene.render(ctx, {"language": "es", "article_color": "amber"})
    same = scene.render(ctx, {"language": "es", "article_color": "white"})
    assert apart.image.get_flattened_data() != same.image.get_flattened_data()


def test_a_word_with_no_article_still_draws(app, tmp_path):
    ctx = ctx_with(app, tmp_path, "- hola = hello\n")
    c = REGISTRY["language"].render(ctx, {"language": "es"})
    assert c.image.get_flattened_data().count((0, 0, 0)) < 192 * 32


def test_recall_hides_the_meaning_then_shows_it(app, tmp_path):
    ctx = ctx_with(app, tmp_path)
    scene = REGISTRY["language"]
    start = datetime.fromtimestamp((int(NOW.timestamp()) // 900) * 900, tz=TZ)

    early = app.context(start + timedelta(seconds=60), brightness=1.0)
    early.vocabulary = ctx.vocabulary
    late = app.context(start + timedelta(seconds=800), brightness=1.0)
    late.vocabulary = ctx.vocabulary

    hidden = scene.render(early, {"language": "es", "reveal": 0.5})
    shown = scene.render(late, {"language": "es", "reveal": 0.5})
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if p != (0, 0, 0))
    assert lit(hidden) < lit(shown)
    # Not blank though -- a half-card with nothing on it looks like a failure.
    assert lit(hidden) > 0


def test_reveal_zero_always_shows_the_meaning(app, tmp_path):
    ctx = ctx_with(app, tmp_path)
    scene = REGISTRY["language"]
    start = datetime.fromtimestamp((int(NOW.timestamp()) // 900) * 900, tz=TZ)
    early = app.context(start + timedelta(seconds=1), brightness=1.0)
    early.vocabulary = ctx.vocabulary
    assert (scene.render(early, {"language": "es", "reveal": 0}).image.get_flattened_data()
            == scene.render(ctx, {"language": "es", "reveal": 0}).image.get_flattened_data())


def test_no_deck_says_so_rather_than_drawing_a_blank(app, tmp_path):
    ctx = app.context(NOW, brightness=1.0)
    ctx.vocabulary = Vocabulary(tmp_path / "nope")
    scene = REGISTRY["language"]
    assert not scene.available(ctx, {"language": "es"})
    c = scene.render(ctx, {"language": "es"})
    assert c.image.get_flattened_data().count((0, 0, 0)) < 192 * 32


# --- placement --------------------------------------------------------------

def every_card(app, books, count=40):
    """Walk the deck a slot at a time, yielding (entry, canvas)."""
    scene = REGISTRY["language"]
    for i in range(count):
        when = NOW + timedelta(seconds=900 * i)
        ctx = app.context(when, brightness=1.0)
        ctx.vocabulary = books
        for code in books.languages:
            entry = books.get(code).at(when, 900, True)
            yield entry, scene.render(ctx, {"language": code, "label": True})


def test_no_card_touches_the_edges(app):
    """See layout.py. The language tag used to sit at x=2, which put every
    card in both decks over the line."""
    from glance.layout import MARGIN
    books = Vocabulary(SHIPPED)
    for entry, canvas in every_card(app, books):
        lit = [x for x in range(canvas.width) for y in range(canvas.height)
               if canvas.image.getpixel((x, y)) != (0, 0, 0)]
        assert min(lit) >= MARGIN, f"{entry.term!r} reaches x={min(lit)}"
        assert max(lit) <= canvas.width - MARGIN, f"{entry.term!r}"


def test_nothing_is_truncated_to_make_room(app):
    """The margin is a floor on the layout, not licence to cut the words.

    Narrowing the room shadowed a variable and every gloss came out clipped to
    26px -- "THE APPLE" as "THE AP.." -- while still passing a margin check,
    because truncated text respects margins beautifully.
    """
    font = get_font("3x5")
    books = Vocabulary(SHIPPED)
    for entry, canvas in every_card(app, books):
        drawn = canvas.to_ascii()
        assert "…" not in drawn and ".." not in entry.gloss
        # The gloss is drawn whole: its full width fits in what it was given.
        assert font.measure(entry.gloss) <= canvas.width - 2 * 8, entry.gloss


def test_the_article_and_the_word_are_centred_together(app, tmp_path):
    """Not the word centred with the article hung off its left edge."""
    ctx = ctx_with(app, tmp_path, "- la granja = the farm\n")
    scene = REGISTRY["language"]
    apart = scene.render(ctx, {"language": "es", "article_color": "amber"})
    lit = [x for x in range(apart.width) for y in range(apart.height)
           if apart.image.getpixel((x, y)) != (0, 0, 0)]
    left, right = min(lit), apart.width - 1 - max(lit)
    assert abs(left - right) <= 4, f"gutters {left} vs {right}"


def test_the_margin_is_adjustable(app, tmp_path):
    ctx = ctx_with(app, tmp_path, "- hola = hello\n")
    scene = REGISTRY["language"]
    edges = {}
    for margin in (0, 24):
        c = scene.render(ctx, {"language": "es", "label": True, "margin": margin})
        lit = [x for x in range(c.width) for y in range(c.height)
               if c.image.getpixel((x, y)) != (0, 0, 0)]
        edges[margin] = min(lit)
    assert edges[24] > edges[0]
