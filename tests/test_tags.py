"""Styling encoded inside calendar entries.

Google's ICS export carries no colour or category data at all, so the only
place styling can live is text that does export: the title and description.
"""

from __future__ import annotations

import pytest

from glance.sources.tags import Style, parse_description, parse_tags, style_for


def test_a_colour_tag_is_lifted_out_of_the_title():
    clean, style = style_for("Take the bins out #amber")
    assert clean == "Take the bins out"
    assert style.color == "amber"


def test_tags_are_stripped_so_they_never_reach_the_panel():
    for raw in ("#red Dentist", "Dentist #red", "Dentist #red #big"):
        clean, _ = style_for(raw)
        assert "#" not in clean
        assert clean.strip() == "Dentist"


def test_an_unknown_hashtag_is_left_alone():
    """'#1 priority' is text, not a directive."""
    clean, style = style_for("Pay the #1 priority invoice")
    assert clean == "Pay the #1 priority invoice"
    assert style.color is None


def test_style_words():
    assert style_for("Dentist #big")[1].style == "hero"
    assert style_for("Old thing #hide")[1].hidden
    assert style_for("Background #quiet")[1].dim
    urgent = style_for("Passport #urgent")[1]
    assert urgent.color == "red" and urgent.priority == 1


def test_multiple_tags_combine():
    clean, style = style_for("Bin day #green #big")
    assert clean == "Bin day"
    assert style.color == "green" and style.style == "hero"


def test_description_keys_are_read():
    style = Style(**{}) if False else style_for("Grange", "color: green\nstyle: hero")[1]
    assert style.color == "green" and style.style == "hero"


def test_only_known_description_keys_are_honoured():
    """A normal description must not accidentally restyle an entry."""
    found = parse_description("notes: bring a coat\nrandom: 5\ncolor: red")
    assert found == {"color": "red"}


def test_a_prose_description_changes_nothing():
    _, style = style_for("Lunch", "Meeting Sam at the cafe, back by two.")
    assert style.color is None and not style.hidden


def test_title_tags_beat_description_keys():
    _, style = style_for("Dentist #red", "color: green")
    assert style.color == "red"


def test_case_is_ignored():
    assert style_for("Thing #AMBER")[1].color == "amber"
    assert style_for("Thing", "COLOR: amber")[1].color == "amber"


def test_hex_colours_survive_the_description():
    assert style_for("Thing", "color: #ff8800")[1].color == "#ff8800"


def test_empty_and_missing_inputs_are_safe():
    assert style_for("", "") == ("", Style())
    assert parse_tags("") == ("", {})
    assert parse_description("") == {}


def test_merged_over_fills_only_what_is_unset():
    base = Style(color="sky", accent="blue", priority=3)
    on_top = Style(color="red")
    merged = on_top.merged_over(base)
    assert merged.color == "red"          # entry wins
    assert merged.accent == "blue"        # calendar default fills in
    assert merged.priority == 3
