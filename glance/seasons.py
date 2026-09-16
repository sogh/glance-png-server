"""When the seasons actually start.

A countdown to autumn cannot use a fixed date. The equinox drifts, because the
tropical year is not a whole number of days and leap years only approximately
correct for it -- across 2020-2040 the September equinox falls on the 22nd in
UTC fourteen times and the 23rd seven times.

Which *local* date that lands on depends entirely on your offset, and this is
the part that makes a hardcoded date a trap rather than merely a shortcut.
Over the same years it is the 22nd every single time in Los Angeles, split
11/10 between the 22nd and 23rd in Berlin, and mostly the 23rd in Auckland. So
"09-22" is a date that happens to be right where it was written and quietly
wrong a few time zones away -- which is the worst kind of wrong to ship, and
the reason this is arithmetic rather than a constant.

So it is computed. Meeus, *Astronomical Algorithms*, chapter 27: a polynomial
for the approximate instant, then a periodic correction from 24 terms. Good to
well under a minute for any year this panel will see, which is rather more
precision than "how many days until autumn" requires -- but the alternative is
a lookup table that runs out.

Meteorological seasons -- the ones that start on the 1st of the month -- are
also offered, because plenty of people mean those. They are simply dates.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# The four moments, named for the month they fall in rather than for a season,
# because which season they begin depends on which half of the planet you are
# standing on.
POINTS = ("march", "june", "september", "december")

# Season -> the point that starts it, per hemisphere.
SEASONS = {
    "north": {"spring": "march", "summer": "june",
              "autumn": "september", "winter": "december"},
    "south": {"autumn": "march", "winter": "june",
              "spring": "september", "summer": "december"},
}
ALIASES = {"fall": "autumn", "autumnal": "autumn", "vernal": "spring"}

# Meeus table 27.C: the periodic terms, as (A, B, C).
_TERMS = (
    (485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186),
    (182, 27.85, 445267.112), (156, 73.14, 45036.886), (136, 171.52, 22518.443),
    (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513),
    (58, 119.81, 33718.147), (52, 297.17, 150.678), (50, 21.02, 2281.226),
    (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
    (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029),
    (14, 199.76, 31436.921), (12, 95.39, 14577.848), (12, 287.11, 31931.756),
    (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074),
)


def _mean_jde(year: int, point: str) -> float:
    """Meeus 27.2 -- the approximate instant, for years 1000 to 3000."""
    y = (year - 2000) / 1000.0
    table = {
        "march":     (2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057),
        "june":      (2451716.56767, 365241.62603, 0.00325, -0.00888, -0.00030),
        "september": (2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078),
        "december":  (2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032),
    }[point]
    return sum(coefficient * y ** power for power, coefficient in enumerate(table))


def _julian_day(year: int, point: str) -> float:
    jde0 = _mean_jde(year, point)
    t = (jde0 - 2451545.0) / 36525.0
    w = math.radians(35999.373 * t - 2.47)
    lam = 1 + 0.0334 * math.cos(w) + 0.0007 * math.cos(2 * w)
    s = sum(a * math.cos(math.radians(b + c * t)) for a, b, c in _TERMS)
    return jde0 + (0.00001 * s) / lam


def _from_julian(jd: float) -> datetime:
    """Julian Day -> UTC datetime. Meeus 7.a, with the fraction kept."""
    jd += 0.5
    z, f = int(jd), jd - int(jd)
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    whole = int(day)
    seconds = round((day - whole) * 86400)
    return (datetime(year, month, whole, tzinfo=timezone.utc)
            + timedelta(seconds=seconds))


def point_at(year: int, point: str) -> datetime:
    """The equinox or solstice named by its month, as a UTC instant."""
    point = str(point).lower()
    if point not in POINTS:
        raise ValueError(f"unknown point {point!r}; expected one of {POINTS}")
    return _from_julian(_julian_day(year, point))


def resolve(name: str, hemisphere: str = "north") -> str:
    """Turn 'fall' or 'autumn' into the month-point that begins it."""
    name = ALIASES.get(str(name).lower(), str(name).lower())
    if name in POINTS:
        return name
    table = SEASONS.get(str(hemisphere).lower(), SEASONS["north"])
    if name not in table:
        raise ValueError(f"unknown season {name!r}")
    return table[name]


def starts_at(year: int, season: str, hemisphere: str = "north",
              tz: ZoneInfo | None = None, meteorological: bool = False) -> datetime:
    """When `season` begins in `year`, in local time."""
    if meteorological:
        month = {"march": 3, "june": 6, "september": 9,
                 "december": 12}[resolve(season, hemisphere)]
        start = datetime(year, month, 1, tzinfo=tz or timezone.utc)
        return start
    moment = point_at(year, resolve(season, hemisphere))
    return moment.astimezone(tz) if tz else moment


def next_start(after: datetime, season: str, hemisphere: str = "north",
               meteorological: bool = False) -> datetime:
    """The next time `season` begins, at or after `after`.

    Rolls into the following year on its own, which is the whole point: a
    fixed date in config is a countdown that expires.
    """
    tz = after.tzinfo
    for year in (after.year, after.year + 1):
        start = starts_at(year, season, hemisphere, tz, meteorological)
        if start >= after:
            return start
    raise RuntimeError("no upcoming season start found")


def days_until(now: datetime, season: str, hemisphere: str = "north",
               meteorological: bool = False) -> int:
    """Whole days from `now` to the start of `season`.

    Counted in calendar days rather than 24-hour blocks: if autumn begins
    tomorrow at any hour, the answer is 1. "In 0 days" on the morning of the
    equinox is correct and is what the scene draws as TODAY.
    """
    start = next_start(now, season, hemisphere, meteorological)
    return (start.date() - now.date()).days
