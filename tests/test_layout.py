"""The centring rule, in one place so it stops being re-derived in four."""

from __future__ import annotations

import pytest

from glance.layout import MARGIN, centre, fits, row, span


def test_content_is_centred():
    assert centre(192, 100) == 46
    assert centre(100, 50, margin=0) == 25


def test_the_margin_is_a_floor_not_an_inset():
    """Narrow content already clears it and is simply centred; only a wide
    row gets pushed."""
    assert centre(192, 20, margin=40) == 86       # centred, well clear
    assert centre(192, 190, margin=8) == 8        # pushed to the floor
    assert centre(192, 500, margin=8) == 8        # and never past it


def test_a_row_is_centred_as_one_group():
    """Not each item centred separately -- that is what let a long board name
    shove the crests across while a short one did not."""
    positions = row(100, [10, 20, 10], gap=5, margin=0)
    used = positions[-1] + 10 - positions[0]
    assert used == span([10, 20, 10], 5) == 50
    assert positions[0] == centre(100, 50, 0) == 25


def test_a_longer_leading_item_moves_the_group_not_the_middle():
    short = row(192, [10, 40], gap=5, margin=MARGIN)
    long_ = row(192, [30, 40], gap=5, margin=MARGIN)
    # The group as a whole shifts; both stay centred about the same point.
    centre_of = lambda p, w: p[0] + (p[-1] + w - p[0]) / 2
    assert centre_of(short, 40) == pytest.approx(centre_of(long_, 40), abs=1)


def test_span_counts_the_gaps_between_and_not_after():
    assert span([10], 5) == 10
    assert span([10, 10], 5) == 25
    assert span([], 5) == 0


def test_fits_accounts_for_both_margins():
    assert fits(192, [80, 80], gap=4, margin=8)
    assert not fits(192, [90, 90], gap=4, margin=8)
