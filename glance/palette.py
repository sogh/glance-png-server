"""Colors tuned for an LED matrix rather than a monitor.

Two things bite you on LED panels that never matter on a screen:

1. Very low non-zero channel values sit at the bottom of the PWM range, where
   panels band and flicker. `snap` pushes near-black to true black.
2. Full-white large areas bloom badly and wash out anything next to them, so
   `WHITE` here is deliberately not 255,255,255.

Accepts the same three color forms the Glance docs use: a name, a hex string,
or an (r, g, b) tuple.
"""

from __future__ import annotations

from typing import Iterable

RGB = tuple[int, int, int]

# Below this, a channel is closer to noise than to light.
PWM_FLOOR = 12

NAMED: dict[str, RGB] = {
    "black": (0, 0, 0),
    "white": (230, 230, 230),
    "hotwhite": (255, 255, 255),
    "red": (255, 40, 30),
    "crimson": (190, 20, 40),
    "orange": (255, 110, 0),
    "amber": (255, 176, 0),
    "yellow": (255, 224, 40),
    "lime": (150, 240, 40),
    "green": (0, 220, 80),
    "forest": (20, 140, 60),
    "mint": (110, 245, 190),
    "teal": (0, 200, 190),
    "cyan": (0, 225, 255),
    "sky": (70, 170, 255),
    "blue": (40, 90, 255),
    "indigo": (110, 70, 240),
    "purple": (170, 70, 255),
    "magenta": (255, 60, 200),
    "pink": (255, 130, 180),
    "brown": (150, 85, 40),
    "grey": (120, 120, 120),
    "gray": (120, 120, 120),
    "dim": (60, 60, 60),
}


def snap(color: RGB) -> RGB:
    """Zero out channels sitting in the panel's unstable low PWM range."""
    return tuple(0 if c < PWM_FLOOR else min(255, c) for c in color)  # type: ignore[return-value]


def parse(value: str | RGB | Iterable[int] | None, default: RGB = (255, 255, 255)) -> RGB:
    """Turn a name, '#rrggbb', '#rgb', or an (r, g, b) triple into RGB."""
    if value is None:
        return default
    if isinstance(value, str):
        key = value.strip().lower()
        if key in NAMED:
            return NAMED[key]
        hexstr = key.lstrip("#")
        if len(hexstr) == 3:
            hexstr = "".join(c * 2 for c in hexstr)
        if len(hexstr) == 6:
            try:
                return (int(hexstr[0:2], 16), int(hexstr[2:4], 16), int(hexstr[4:6], 16))
            except ValueError:
                pass
        raise ValueError(f"cannot parse color {value!r}")
    r, g, b = (int(c) for c in value)  # type: ignore[misc]
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def dim(color: str | RGB, factor: float) -> RGB:
    """Scale brightness. Mirrors the `color.dim()` helper in Glance's own SDK."""
    r, g, b = parse(color)
    factor = max(0.0, factor)
    return snap((int(r * factor), int(g * factor), int(b * factor)))


def mix(a: str | RGB, b: str | RGB, t: float) -> RGB:
    """Linear blend; t=0 gives a, t=1 gives b."""
    ar, ag, ab = parse(a)
    br, bg, bb = parse(b)
    t = max(0.0, min(1.0, t))
    return snap(
        (
            int(ar + (br - ar) * t),
            int(ag + (bg - ag) * t),
            int(ab + (bb - ab) * t),
        )
    )
