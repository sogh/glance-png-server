"""Moon phase, computed rather than fetched.

The synodic month is regular enough that a reference new moon plus arithmetic
lands within a few hours, which is far better than a 40-pixel disc can show.
No API, no integration, works offline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

# A known new moon, and the mean length of a lunation.
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
SYNODIC_MONTH = 29.530588853

NAMES = [
    (0.020, "NEW"),
    (0.240, "WAXING CRESCENT"),
    (0.280, "FIRST QUARTER"),
    (0.480, "WAXING GIBBOUS"),
    (0.520, "FULL"),
    (0.720, "WANING GIBBOUS"),
    (0.780, "LAST QUARTER"),
    (0.980, "WANING CRESCENT"),
    (1.001, "NEW"),
]
SHORT = {
    "NEW": "NEW", "WAXING CRESCENT": "WAX CRES", "FIRST QUARTER": "FIRST QTR",
    "WAXING GIBBOUS": "WAX GIBB", "FULL": "FULL", "WANING GIBBOUS": "WAN GIBB",
    "LAST QUARTER": "LAST QTR", "WANING CRESCENT": "WAN CRES",
}


@dataclass
class Moon:
    phase: float          # 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter
    age_days: float
    illumination: float   # 0..1

    @property
    def waxing(self) -> bool:
        return self.phase < 0.5

    @property
    def name(self) -> str:
        for ceiling, label in NAMES:
            if self.phase < ceiling:
                return label
        return "NEW"

    @property
    def short_name(self) -> str:
        return SHORT.get(self.name, self.name)


def phase_at(when: datetime | None = None) -> Moon:
    when = when or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    days = (when - REFERENCE_NEW_MOON).total_seconds() / 86400.0
    phase = (days % SYNODIC_MONTH) / SYNODIC_MONTH
    return Moon(
        phase=phase,
        age_days=phase * SYNODIC_MONTH,
        illumination=(1.0 - math.cos(2.0 * math.pi * phase)) / 2.0,
    )


# The dark plains, roughly where they actually are: the moon is tidally
# locked, so the same face is always turned toward us and the pattern is
# fixed. Positions are fractions of the radius, x right and y down, which
# keeps them correct at any size.
#
#   Imbrium upper left, Serenitatis and Tranquillitatis upper right,
#   Procellarum down the left flank, Crisium a dot near the right limb,
#   Nubium and Nectaris along the bottom.
MARIA = (
    (-0.34, -0.36, 0.30),    # Imbrium
    (0.14, -0.34, 0.22),     # Serenitatis
    (0.36, -0.10, 0.24),     # Tranquillitatis
    (0.66, -0.26, 0.12),     # Crisium
    (-0.58, 0.04, 0.26),     # Procellarum
    (-0.26, 0.40, 0.20),     # Nubium
    (0.34, 0.34, 0.16),      # Nectaris
)

# The seven plains need room. Much under a seven pixel radius the small ones
# shrink to a pixel apiece -- Crisium is a lone dark dot at radius six, which
# reads as a dead sub-pixel -- and the boundary of the rest turns ragged
# enough to look like dither. Smaller discs get the two masses the eye
# actually picks out instead: Imbrium with Procellarum, and Serenitatis with
# Tranquillitatis.
MARIA_COARSE = (
    (-0.30, -0.30, 0.46),
    (0.34, -0.14, 0.38),
)

FINE_MARIA_RADIUS = 7


def in_mare(x: float, y: float, radius: float) -> bool:
    """Whether a point on the disc falls on one of the dark plains."""
    if radius <= 0:
        return False
    table = MARIA if radius >= FINE_MARIA_RADIUS else MARIA_COARSE
    for nx, ny, nr in table:
        dx = x - nx * radius
        dy = y - ny * radius
        # A slight inset. A plain otherwise claims every pixel whose centre is
        # barely inside, and the maria creep past the third of the near side
        # they really cover.
        limit = nr * radius - 0.1
        if limit > 0.0 and dx * dx + dy * dy <= limit * limit:
            return True
    return False


def lit(x: float, y: float, radius: float, phase: float) -> bool:
    """Whether a point inside the disc is in sunlight.

    The terminator is an ellipse seen edge-on, so its half-width at a given
    height scales with cos(2*pi*phase): +1 at new (nothing lit), 0 at the
    quarters (a straight edge), -1 at full (everything lit).
    """
    if x * x + y * y > radius * radius:
        return False

    # At the extremes the terminator lies exactly along the limb, and the
    # comparison below is degenerate: at new moon `edge` equals the half-width
    # so the outermost pixel of every row satisfies `x >= edge`, lighting a
    # rim on a disc that should be entirely dark. Settle those two cases
    # outright rather than leaning on floating point to land the right way.
    illumination = (1.0 - math.cos(2.0 * math.pi * phase)) / 2.0
    if illumination <= 0.005:
        return False
    if illumination >= 0.995:
        return True

    half = math.sqrt(max(0.0, radius * radius - y * y))
    if half < 1.0:
        # The terminator passes through both poles at every phase, so those
        # pixels are on it whatever the phase. Let them follow the disc.
        return illumination >= 0.5

    edge = math.cos(2.0 * math.pi * phase) * half
    return x >= edge if phase <= 0.5 else x <= -edge
