"""Team logos reduced to something a 32px LED panel can show."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest
from PIL import Image

from glance.sources.logos import (INK_FLOOR, MIN_INK, LogoStore, ink, luminance,
                                  normalise, prepare, reduce_to)


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def block(colour, size=500, mode="RGBA", pad=0):
    """A solid square, optionally inset in transparent padding."""
    img = Image.new(mode, (size, size), (0, 0, 0, 0) if mode == "RGBA" else (0, 0, 0))
    fill = Image.new(mode, (size - pad * 2, size - pad * 2),
                     colour if mode == "RGBA" else colour[:3])
    img.paste(fill, (pad, pad))
    return img


def wait_for(store: LogoStore, seconds: float = 10.0) -> None:
    deadline = time.time() + seconds
    while store.pending and time.time() < deadline:
        time.sleep(0.01)
    assert not store.pending, "background fetch never finished"


# --- the reduction ----------------------------------------------------------

def test_a_logo_is_reduced_to_a_square_of_the_asked_size():
    out = reduce_to(block((255, 255, 255, 255)), 16)
    assert out.size == (16, 16)
    assert out.mode == "RGB"


def test_transparency_is_flattened_onto_black_not_white():
    """A panel is unlit where nothing is drawn. Compositing onto white would
    turn every transparent area into a bright patch.

    The hole is punched in the middle rather than left as a margin, because a
    margin gets trimmed away before any of this -- see the next test."""
    ring = Image.new("RGBA", (500, 500), (255, 255, 255, 255))
    ring.paste(Image.new("RGBA", (200, 200), (0, 0, 0, 0)), (150, 150))
    out = reduce_to(ring, 16)
    assert out.getpixel((8, 8)) == (0, 0, 0)
    assert luminance(out.getpixel((1, 1))) > 200


def test_transparent_padding_is_trimmed_before_scaling():
    """Otherwise a logo drawn small inside a large canvas keeps that margin
    and ends up half the size it was given."""
    padded = reduce_to(block((255, 255, 255, 255), pad=200), 16)
    tight = reduce_to(block((255, 255, 255, 255)), 16)
    assert ink(padded) == pytest.approx(ink(tight), abs=0.05)
    assert ink(padded) > 0.9


def test_a_wide_logo_keeps_its_shape_and_is_centred():
    wide = Image.new("RGBA", (400, 100), (255, 255, 255, 255))
    out = reduce_to(wide, 16)
    assert out.size == (16, 16)
    # Letterboxed: dark at the top, lit through the middle.
    assert luminance(out.getpixel((8, 0))) < INK_FLOOR
    assert luminance(out.getpixel((8, 8))) >= INK_FLOOR


def test_an_empty_image_does_not_explode():
    assert reduce_to(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), 16).size == (16, 16)


# --- brightness -------------------------------------------------------------

def test_a_dim_logo_is_lifted_towards_the_target_peak():
    """Arkansas's dark red hog peaks at 85 of 255 on black and is invisible on
    a panel. Lifting it makes it a legible silhouette."""
    dim_red = reduce_to(block((85, 10, 10, 255)), 16)
    before = max(luminance(p) for p in dim_red.get_flattened_data())
    after = max(luminance(p) for p in normalise(dim_red).get_flattened_data())
    assert before < 60
    assert after > before * 2


def test_an_already_bright_logo_is_left_alone():
    bright = reduce_to(block((255, 255, 255, 255)), 16)
    assert normalise(bright).get_flattened_data() == bright.get_flattened_data()


def test_the_gain_is_clamped_so_noise_is_not_amplified():
    """A near-black image must not be multiplied into a grey rectangle."""
    nearly = reduce_to(block((3, 3, 3, 255)), 16)
    lifted = normalise(nearly)
    assert max(luminance(p) for p in lifted.get_flattened_data()) < 20


# --- the readability guard --------------------------------------------------

def test_a_logo_with_almost_no_ink_is_refused():
    """A shape too thin to survive the reduction is a smudge, not a logo --
    better to print the abbreviation, which always reads.

    Note this has to be sparse across its OWN bounding box. A small mark in a
    large transparent canvas is just a padded logo, and gets trimmed and
    scaled up rather than rejected.
    """
    sparse = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    for corner in ((0, 0), (496, 0), (0, 496), (496, 496)):
        sparse.paste(Image.new("RGBA", (4, 4), (255, 255, 255, 255)), corner)
    assert prepare(sparse, 16) is None


def test_a_small_mark_in_a_big_canvas_is_scaled_up_not_rejected():
    """Logos are routinely exported with generous padding. Trimming it is the
    difference between filling the box and occupying a quarter of it."""
    padded = Image.new("RGBA", (500, 500), (0, 0, 0, 0))
    padded.paste(Image.new("RGBA", (40, 40), (255, 255, 255, 255)), (230, 230))
    out = prepare(padded, 16)
    assert out is not None
    assert ink(out) > 0.9


def test_a_solid_logo_passes():
    out = prepare(block((200, 40, 40, 255)), 16)
    assert out is not None
    assert ink(out) >= MIN_INK


# --- the store --------------------------------------------------------------

@pytest.fixture
def served(monkeypatch):
    """Serve PNGs from an in-memory table, counting requests."""
    import glance.sources.logos as mod

    table = {"good": png_bytes(block((220, 60, 60, 255))),
             "faint": png_bytes(Image.new("RGBA", (500, 500), (0, 0, 0, 0)))}
    calls: list[str] = []

    class Resp:
        def __init__(self, body): self.content = body
        def raise_for_status(self): pass

    def fake_get(url, **kwargs):
        calls.append(url)
        name = str(url).rsplit("/", 1)[-1]
        if name not in table:
            raise OSError("404")
        return Resp(table[name])

    monkeypatch.setattr(mod.httpx, "get", fake_get)
    return calls


def test_a_cold_lookup_returns_nothing_and_fetches_in_the_background(tmp_path, served):
    """The device gives up after about four seconds. A render must never wait
    on a download, so the first look is a miss and the next one has it."""
    store = LogoStore(tmp_path, size=16)
    started = time.perf_counter()
    assert store.get("t", ["http://x/good"]) is None
    assert time.perf_counter() - started < 0.2, "get() blocked on the network"
    wait_for(store)
    assert store.get("t", ["http://x/good"]) is not None


def test_the_second_lookup_comes_from_disk_without_refetching(tmp_path, served):
    store = LogoStore(tmp_path, size=16)
    store.get("t", ["http://x/good"]); wait_for(store)
    fetches = len(served)
    fresh = LogoStore(tmp_path, size=16)          # cold memo, warm disk
    assert fresh.get("t", ["http://x/good"]) is not None
    assert len(served) == fetches, "refetched something already on disk"


def test_one_download_per_team_not_one_per_render(tmp_path, served):
    store = LogoStore(tmp_path, size=16)
    for _ in range(5):
        store.get("t", ["http://x/good"])
    wait_for(store)
    assert len(served) == 1


def test_a_logo_that_will_not_read_is_remembered_as_such(tmp_path, served):
    """Otherwise every render re-downloads and re-tests the same dud."""
    store = LogoStore(tmp_path, size=16)
    store.get("t", ["http://x/faint"]); wait_for(store)
    assert store.get("t", ["http://x/faint"]) is None
    fetches = len(served)
    LogoStore(tmp_path, size=16).get("t", ["http://x/faint"])
    assert len(served) == fetches


def test_the_brightest_candidate_wins(tmp_path, monkeypatch):
    """ESPN's dark variant is listed first, but the decision is made on what
    actually reads, not on the order of the list."""
    import glance.sources.logos as mod

    class Resp:
        def __init__(self, body): self.content = body
        def raise_for_status(self): pass

    bodies = {"dim": png_bytes(block((70, 70, 70, 255))),
              "bright": png_bytes(block((255, 255, 255, 255)))}
    monkeypatch.setattr(mod.httpx, "get",
                        lambda url, **k: Resp(bodies[str(url).rsplit("/", 1)[-1]]))
    store = LogoStore(tmp_path, size=16)
    store.get("t", ["http://x/dim", "http://x/bright"]); wait_for(store)
    out = store.get("t", ["http://x/dim", "http://x/bright"])
    assert max(luminance(p) for p in out.get_flattened_data()) > 200


def test_a_dead_url_is_not_an_outage(tmp_path, served):
    store = LogoStore(tmp_path, size=16)
    assert store.get("t", ["http://x/missing"]) is None
    wait_for(store)
    assert store.get("t", ["http://x/missing"]) is None


def test_no_url_at_all_is_answered_immediately(tmp_path, served):
    store = LogoStore(tmp_path, size=16)
    assert store.get("t", []) is None
    assert store.get("t", "") is None
    assert not served


def test_a_corrupt_cache_file_is_discarded_rather_than_raised(tmp_path, served):
    store = LogoStore(tmp_path, size=16)
    store.get("t", ["http://x/good"]); wait_for(store)
    store._rendered("t").write_bytes(b"not a png")
    fresh = LogoStore(tmp_path, size=16)
    assert fresh.get("t", ["http://x/good"]) is None    # discarded, refetching
    wait_for(fresh)
    assert fresh.get("t", ["http://x/good"]) is not None


def test_sizes_are_cached_separately(tmp_path, served):
    small = LogoStore(tmp_path, size=12)
    big = LogoStore(tmp_path, size=24)
    small.get("t", ["http://x/good"]); wait_for(small)
    big.get("t", ["http://x/good"]); wait_for(big)
    assert small.get("t", ["http://x/good"]).size == (12, 12)
    assert big.get("t", ["http://x/good"]).size == (24, 24)
