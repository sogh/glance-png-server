"""Time-of-day brightness.

An LED matrix at full output in a dark room is unpleasant, and every scene
would otherwise have to think about it. So this is applied once, to the
finished canvas, on the way out.

The schedule is a list of (time, level) points and the level ramps linearly
between them, wrapping through midnight. A ramp rather than a step means the
panel never visibly jumps while you are looking at it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

# Flat through the day, then down through the evening. The 20:00 point is
# what keeps the daytime flat: without it the level ramps from breakfast to
# bedtime and noon comes out dimmer than dawn.
DEFAULT_SCHEDULE = [
    ("06:00", 0.15),    # pre-dawn floor
    ("07:30", 1.00),    # sunrise ramp finishes
    ("20:00", 1.00),    # hold full all day
    ("22:00", 0.45),    # evening
    ("23:30", 0.22),    # night
]


def _minutes(stamp: str) -> int:
    hour, _, minute = str(stamp).partition(":")
    return (int(hour) % 24) * 60 + int(minute or 0)


@dataclass
class Brightness:
    points: list[tuple[int, float]]
    floor: float = 0.05
    enabled: bool = True

    @classmethod
    def from_config(cls, spec: Any) -> "Brightness":
        if spec is None or spec is True:
            spec = {}
        if spec is False:
            return cls(points=[(0, 1.0)], enabled=False)
        if isinstance(spec, (int, float)):
            return cls(points=[(0, float(spec))])

        raw: Iterable[Any] = (spec or {}).get("schedule") or DEFAULT_SCHEDULE
        points: list[tuple[int, float]] = []
        for item in raw:
            if isinstance(item, dict):
                points.append((_minutes(item["at"]), float(item["level"])))
            else:
                at, level = item
                points.append((_minutes(at), float(level)))
        points.sort()
        return cls(
            points=points or [(0, 1.0)],
            floor=float((spec or {}).get("floor", 0.05)),
            enabled=bool((spec or {}).get("enabled", True)),
        )

    def level_at(self, now: datetime) -> float:
        if not self.enabled or len(self.points) == 1:
            return max(self.floor, self.points[0][1]) if self.points else 1.0

        minute = now.hour * 60 + now.minute
        pts = self.points

        # Find the bracket, treating the list as a circle so the last point of
        # the evening ramps into the first of the morning.
        previous = pts[-1]
        following = pts[0]
        for index, point in enumerate(pts):
            if point[0] > minute:
                following = point
                previous = pts[index - 1]
                break
        else:
            previous, following = pts[-1], pts[0]

        span = (following[0] - previous[0]) % (24 * 60) or 24 * 60
        into = (minute - previous[0]) % (24 * 60)
        t = min(1.0, into / span)
        level = previous[1] + (following[1] - previous[1]) * t
        return max(self.floor, min(1.0, level))


def apply(canvas, level: float) -> None:
    """Scale a canvas in place.

    A lit pixel never goes fully dark: scaling a dim colour by 0.15 would
    round it to black and punch holes in the artwork, so anything that was on
    stays on, however faintly.
    """
    if level >= 0.999:
        return
    image = canvas.image
    px = image.load()
    for y in range(image.height):
        for x in range(image.width):
            r, g, b = px[x, y]
            if r or g or b:
                px[x, y] = (
                    max(1, int(r * level)) if r else 0,
                    max(1, int(g * level)) if g else 0,
                    max(1, int(b * level)) if b else 0,
                )
