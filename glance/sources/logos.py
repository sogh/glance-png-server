"""Team logos, reduced to something an LED matrix can actually show.

A crest drawn for a screen is not a crest that survives being 14 pixels wide,
and most of the work here is deciding when to give up and print the
abbreviation instead.

Three things matter, in order:

**Scale down with area averaging, not nearest neighbour.** Everywhere else in
this codebase scaling is nearest and hard-edged, because enlarging pixel art
any other way makes mud. Going the other way -- 500px down to 14 -- the rule
inverts: nearest throws away 99.9% of the pixels and keeps whichever ones
happen to land on the sample grid, which turns a thin outline into dashes.

**Prefer the dark variant.** ESPN publishes a `500-dark` logo meant for dark
backgrounds, and on black it is dramatically better for anything navy: Notre
Dame's peak luminance goes 87 -> 173, Indiana's 41 -> 255. Where no separate
dark version exists the two are the same file and nothing is lost.

**Normalise the peak.** These files are built for a bright screen. Arkansas's
dark red hog peaks at 85 of 255 on black and is invisible on a panel; scaling
it so the brightest pixel lands near 230 makes it a legible silhouette. The
gain is clamped so an almost-empty image is not amplified into noise.

And then the guard: if after all that the logo still lights too few pixels, it
is not a logo at this size, it is a smudge. Return nothing and let the caller
print the abbreviation, which always reads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Iterable

import httpx
from PIL import Image

log = logging.getLogger(__name__)

# 14px is the floor. Below it the detailed crests -- Notre Dame's interlocking
# ND, Ohio State's buckeye -- collapse into noise; at 14 they read.
MIN_SIZE = 8
DEFAULT_SIZE = 16

TARGET_PEAK = 230.0       # brightest pixel after normalising
MAX_GAIN = 4.0            # do not amplify an almost-empty image into noise
INK_FLOOR = 40            # luminance an LED shows clearly
MIN_INK = 0.08            # below this share of lit pixels it is a smudge

RAW_TTL = 30 * 86400      # logos change about once a decade


def luminance(pixel: tuple[int, int, int]) -> float:
    r, g, b = pixel
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _slug(text: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").lower()
    return clean or hashlib.sha256(str(text).encode()).hexdigest()[:12]


def reduce_to(source: Image.Image, size: int) -> Image.Image:
    """Flatten onto black and area-average down to `size` square."""
    rgba = source.convert("RGBA")
    # Trim fully transparent margins first, or a logo with generous padding
    # ends up occupying half the box it was given.
    box = rgba.getbbox()
    if box:
        rgba = rgba.crop(box)
    flat = Image.alpha_composite(Image.new("RGBA", rgba.size, (0, 0, 0, 255)), rgba)

    # Fit the long edge, keeping the aspect ratio, then centre it in a square.
    wide, tall = flat.size
    if wide <= 0 or tall <= 0:
        return Image.new("RGB", (size, size), (0, 0, 0))
    scale = size / max(wide, tall)
    target = (max(1, round(wide * scale)), max(1, round(tall * scale)))
    small = flat.convert("RGB").resize(target, Image.LANCZOS)

    out = Image.new("RGB", (size, size), (0, 0, 0))
    out.paste(small, ((size - target[0]) // 2, (size - target[1]) // 2))
    return out


def normalise(image: Image.Image) -> Image.Image:
    """Lift the brightest pixel towards TARGET_PEAK, within a clamp."""
    pixels = list(image.get_flattened_data())
    if not pixels:
        return image
    peak = max(luminance(p) for p in pixels)
    if peak < 1.0:
        return image
    gain = min(MAX_GAIN, TARGET_PEAK / peak)
    if gain <= 1.01:
        return image
    return image.point(lambda v: min(255, int(v * gain)))


def ink(image: Image.Image) -> float:
    """Share of pixels bright enough for the panel to show."""
    pixels = list(image.get_flattened_data())
    if not pixels:
        return 0.0
    return sum(1 for p in pixels if luminance(p) >= INK_FLOOR) / len(pixels)


def prepare(source: Image.Image, size: int) -> Image.Image | None:
    """The whole pipeline. None means "this will not read; use text"."""
    small = normalise(reduce_to(source, size))
    return small if ink(small) >= MIN_INK else None


class LogoStore:
    """Fetches, reduces and caches logos, keyed by however you name a team."""

    def __init__(self, cache_dir: Path, size: int = DEFAULT_SIZE,
                 timeout: float = 12.0) -> None:
        self.size = max(MIN_SIZE, int(size))
        self.timeout = timeout
        self.dir = Path(cache_dir) / "logos"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._memo: dict[str, Image.Image | None] = {}
        self._pending: set[str] = set()

    # --- disk ---------------------------------------------------------------

    def _raw(self, key: str, url: str) -> Path | None:
        """The original download, kept so a resize never refetches."""
        path = self.dir / f"raw-{_slug(key)}"
        if path.exists() and time.time() - path.stat().st_mtime < RAW_TTL:
            return path
        try:
            resp = httpx.get(url, timeout=self.timeout, follow_redirects=True)
            resp.raise_for_status()
            path.write_bytes(resp.content)
            return path
        except Exception as exc:  # noqa: BLE001 - a missing logo is not an outage
            self.last_error = f"{key}: {type(exc).__name__}: {exc}"
            return path if path.exists() else None

    def _rendered(self, key: str) -> Path:
        return self.dir / f"{_slug(key)}-{self.size}.png"

    # --- api ----------------------------------------------------------------

    def get(self, key: str, urls: str | Iterable[str]) -> Image.Image | None:
        """The panel-ready logo for `key`, or None if it is not ready yet.

        **Never blocks on the network.** The device gives up on a fetch after
        about four seconds, and a cold cache means several downloads; doing
        them inline would time the panel out and show nothing at all. So a
        miss returns None -- the caller draws the abbreviation, which always
        works -- and the download happens on a background thread. The next
        refresh a minute later has the logo.

        `urls` may be several candidates in preference order (the dark variant
        first); the brightest usable one wins.
        """
        if isinstance(urls, str):
            urls = [urls]
        urls = [u for u in urls if u]
        if not urls:
            return None

        memo_key = f"{key}:{self.size}"
        with self._lock:
            if memo_key in self._memo:
                return self._memo[memo_key]
            cached = self._from_disk(key)
            if cached is not None:
                self._memo[memo_key] = cached
                return cached
            if self._missing(key):
                self._memo[memo_key] = None
                return None
            if memo_key not in self._pending:
                self._pending.add(memo_key)
                threading.Thread(target=self._fetch_later, args=(memo_key, key, urls),
                                 daemon=True, name=f"logo-{_slug(key)}").start()
        return None

    def _fetch_later(self, memo_key: str, key: str, urls: list[str]) -> None:
        try:
            result = self._build(key, urls)
        except Exception as exc:  # noqa: BLE001 - a background thread must not die loudly
            # Warning, not info: this thread is the only thing that ever runs
            # this code, so a bug in it is otherwise completely silent -- the
            # panel just quietly shows text forever.
            log.warning("logo %s failed: %s: %s", key, type(exc).__name__, exc)
            self.last_error = f"{key}: {type(exc).__name__}: {exc}"
            result = None
        with self._lock:
            self._memo[memo_key] = result
            self._pending.discard(memo_key)

    def _from_disk(self, key: str) -> Image.Image | None:
        rendered = self._rendered(key)
        if not rendered.exists():
            return None
        try:
            with Image.open(rendered) as cached:
                return cached.convert("RGB")
        except Exception:  # noqa: BLE001 - a corrupt cache file is not fatal
            rendered.unlink(missing_ok=True)
            return None

    def _missing(self, key: str) -> bool:
        """Whether this team is already known to have no usable logo."""
        marker = self.dir / f"{_slug(key)}-{self.size}.none"
        return marker.exists() and time.time() - marker.stat().st_mtime < RAW_TTL

    @property
    def pending(self) -> int:
        """How many logos are still being fetched. For /api/status."""
        with self._lock:
            return len(self._pending)

    def _build(self, key: str, urls: list[str]) -> Image.Image | None:
        """Download, reduce and test. Runs on a background thread."""
        cached = self._from_disk(key)
        if cached is not None:
            return cached
        # A marker, so a team with no usable logo is not re-fetched and
        # re-tested on every render.
        miss = self.dir / f"{_slug(key)}-{self.size}.none"
        if self._missing(key):
            return None

        best: Image.Image | None = None
        best_peak = -1.0
        for index, url in enumerate(urls):
            path = self._raw(f"{key}-{index}", url)
            if path is None:
                continue
            try:
                with Image.open(path) as source:
                    candidate = reduce_to(source, self.size)
            except Exception as exc:  # noqa: BLE001
                self.last_error = f"{key}: {type(exc).__name__}: {exc}"
                continue
            peak = max((luminance(p) for p in candidate.get_flattened_data()), default=0.0)
            if peak > best_peak:
                best, best_peak = candidate, peak

        if best is None:
            return None
        finished = normalise(best)
        if ink(finished) < MIN_INK:
            log.info("logo %s does not read at %dpx; using text", key, self.size)
            miss.touch()
            return None
        try:
            finished.save(self._rendered(key))
        except OSError:
            pass          # caching is a nicety
        return finished

    def warm(self, entries: Iterable[tuple[str, Iterable[str]]]) -> None:
        """Ask for several logos at once, so the first panel after a restart
        has them rather than showing text for one refresh."""
        for key, urls in entries:
            self.get(key, urls)

    def clear_memo(self) -> None:
        with self._lock:
            self._memo.clear()
            self._pending.clear()
