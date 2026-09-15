"""Instagram counts.

The point of this scene is not that it fetches numbers -- it is that it never
shows one it cannot stand behind. Scraping the public profile returns a login
wall intermittently, and an app built on that presents stale or zero values as
fact, which is how a panel ends up confidently wrong.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from glance.scenes import REGISTRY
from glance.scenes.instagram import human
from glance.sources.instagram import InstagramSource, Profile


def test_numbers_stay_exact_until_they_stop_fitting():
    assert human(7) == "7"
    assert human(1284) == "1,284"
    assert human(9999) == "9,999"
    assert human(12400) == "12.4K"
    assert human(1_260_000) == "1.3M"
    # .5 ties round to even, as Python formats them. Irrelevant at this scale,
    # but worth pinning so it is a decision rather than a surprise.
    assert human(1_250_000) == "1.2M"


def test_age_is_reported_in_useful_units():
    now = time.time()
    assert Profile("x", 1, 1, fetched_at=now - 300).age_text(now) == "5M"
    assert Profile("x", 1, 1, fetched_at=now - 7200).age_text(now) == "2H"
    assert Profile("x", 1, 1, fetched_at=now - 3 * 86400).age_text(now) == "3D"


def test_own_account_payload():
    p = InstagramSource._parse(
        {"username": "sample_account", "name": "Sample Account",
         "followers_count": 1284, "media_count": 317, "follows_count": 190}, "")
    assert (p.followers, p.posts, p.follows) == (1284, 317, 190)
    assert p.username == "sample_account"


def test_business_discovery_payload():
    """A different shape entirely -- the counts arrive nested."""
    p = InstagramSource._parse(
        {"business_discovery": {"username": "sample_account",
                                "followers_count": 1284, "media_count": 317}},
        "sample_account")
    assert (p.followers, p.posts) == (1284, 317)
    assert p.follows is None


def test_without_a_token_it_says_so(tmp_path: Path):
    src = InstagramSource("", "sample_account", cache_dir=tmp_path)
    assert not src.configured
    assert src.profile() is None
    assert "token" in src.last_error


def test_a_fresh_cache_is_used_without_calling_out(tmp_path: Path):
    src = InstagramSource("tok", "sample_account", cache_dir=tmp_path, refresh=9999)
    src.cache_file.write_text(json.dumps(
        Profile("sample_account", 1284, 317, fetched_at=time.time()).__dict__))
    p = src.profile()
    assert p.followers == 1284
    assert src.last_error is None, "should not have attempted a request"


def test_a_failed_fetch_serves_the_last_known_numbers(tmp_path: Path):
    """Stale and labelled beats absent, and beats wrong."""
    src = InstagramSource("bad-token", "sample_account", cache_dir=tmp_path, refresh=0)
    old = time.time() - 6 * 3600
    src.cache_file.write_text(json.dumps(
        Profile("sample_account", 1284, 317, fetched_at=old).__dict__))
    src.timeout = 0.001
    p = src.profile()
    assert p is not None and p.followers == 1284
    assert src.last_error, "the failure is still recorded"
    assert p.age_text().endswith("H")


def test_no_cache_and_no_network_yields_nothing_rather_than_zero(tmp_path: Path):
    """Zero followers is a number. Showing it would be a lie."""
    src = InstagramSource("bad-token", "sample_account", cache_dir=tmp_path, refresh=0)
    src.timeout = 0.001
    assert src.profile() is None


# --- the scene --------------------------------------------------------------

class Fake:
    configured = True

    def __init__(self, profile, error=None):
        self._p, self.last_error = profile, error

    def profile(self):
        return self._p


def render(app, source, params=None):
    ctx = app.context(brightness=1.0)
    ctx.instagram = source
    return REGISTRY["instagram"].render(ctx, params or {})


def test_it_draws_both_counts(app):
    c = render(app, Fake(Profile("sample_account", 1284, 317, fetched_at=time.time())))
    assert c.image.size == (192, 32)
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) > 200


def test_fresh_numbers_carry_no_age_marker(app):
    fresh = render(app, Fake(Profile("e", 1284, 317, fetched_at=time.time())))
    stale = render(app, Fake(Profile("e", 1284, 317, fetched_at=time.time() - 6 * 3600)))
    lit = lambda c: sum(1 for p in c.image.get_flattened_data() if sum(p) > 0)
    assert lit(stale) > lit(fresh), "an old number should announce its age"


def test_the_age_marker_is_amber_not_silent(app):
    c = render(app, Fake(Profile("e", 1284, 317, fetched_at=time.time() - 99999)))
    ambers = [p for p in c.image.get_flattened_data()
              if p[0] > 200 and 120 < p[1] < 220 and p[2] < 80]
    assert ambers


def test_the_staleness_threshold_is_configurable(app):
    old = Profile("e", 1284, 317, fetched_at=time.time() - 3600)
    quiet = render(app, Fake(old), {"stale_after": 99999})
    loud = render(app, Fake(old), {"stale_after": 60})
    assert quiet.to_ascii() != loud.to_ascii()


def test_no_data_explains_itself_instead_of_showing_zero(app):
    c = render(app, Fake(None, error="OAuthException: token expired"))
    art = c.to_ascii()
    assert "#" in art, "should say something"
    # No large digits: a zero count must never be drawn as though it were real.
    assert sum(1 for p in c.image.get_flattened_data() if sum(p) > 0) < 400


def test_it_drops_out_of_rotation_when_unconfigured(app, now):
    ctx = app.context(now)
    ctx.instagram = None
    assert not REGISTRY["instagram"].available(ctx, {})
    assert REGISTRY["instagram"].available(ctx, {"always": True})


def test_long_handles_do_not_overflow(app):
    c = render(app, Fake(Profile("a" * 40, 1284, 317, fetched_at=time.time())))
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(6, 32)]
    assert all(sum(p) == 0 for p in edge)


def test_big_numbers_do_not_collide(app):
    c = render(app, Fake(Profile("e", 987654, 54321, fetched_at=time.time())))
    edge = [c.image.getpixel((c.width - 1, y)) for y in range(32)]
    assert all(sum(p) == 0 for p in edge)


def test_the_at_sign_is_not_a_question_mark():
    """It was, until the 3x5 font learned the glyph."""
    from glance.fonts import FONT_3X5
    assert "@" in FONT_3X5.source
