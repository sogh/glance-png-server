"""Bitmap fonts for the Glance LED panel.

At 32px tall, anti-aliased TrueType text turns to grey mush: every glyph edge
becomes a half-lit LED. So text here is drawn from hand-authored bitmap glyphs
where every pixel is either on or off.

Glyphs are stored as human-editable pixel art -- '#' is lit, '.' is dark, and
rows are separated by '/'. Tweaking a letter means editing the string; there is
no font file to regenerate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image

# --- 5x7: the workhorse. Full printable ASCII. ------------------------------
# Lowercase descenders (g j p q y) sit one row high so their tails fit inside
# the 7-row cell. That 1px baseline compromise is what real 5x7 LED ROMs do.
FONT_5X7_GLYPHS: dict[str, str] = {
    " ": "...../...../...../...../...../...../.....",
    "!": "..#../..#../..#../..#../..#../...../..#..",
    '"': ".#.#./.#.#./...../...../...../...../.....",
    "#": ".#.#./.#.#./#####/.#.#./#####/.#.#./.#.#.",
    "$": "..#../.####/#.#../.###./..#.#/####./..#..",
    "%": "##.../##..#/...#./..#../.#.../#..##/...##",
    "&": ".##../#..#./#.#../.#.../#.#.#/#..#./.##.#",
    "'": "..#../..#../...../...../...../...../.....",
    "(": "...#./..#../.#.../.#.../.#.../..#../...#.",
    ")": ".#.../..#../...#./...#./...#./..#../.#...",
    "*": "...../#.#.#/.###./#####/.###./#.#.#/.....",
    "+": "...../..#../..#../#####/..#../..#../.....",
    ",": "...../...../...../...../..##./..#../.#...",
    "-": "...../...../...../#####/...../...../.....",
    ".": "...../...../...../...../...../.##../.##..",
    "/": "....#/...#./..#../.#.../#..../...../.....",
    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####",
    "3": "#####/...#./..#../...#./....#/#...#/.###.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.",
    "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": "..##./.#.../#..../####./#...#/#...#/.###.",
    "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.",
    "9": ".###./#...#/#...#/.####/....#/...#./.##..",
    ":": "...../.##../.##../...../.##../.##../.....",
    ";": "...../.##../.##../...../.##../..#../.#...",
    "<": "...#./..#../.#.../#..../.#.../..#../...#.",
    "=": "...../...../#####/...../#####/...../.....",
    ">": ".#.../..#../...#./....#/...#./..#../.#...",
    "?": ".###./#...#/....#/...#./..#../...../..#..",
    "@": ".###./#...#/....#/.##.#/#.#.#/#.#.#/.##..",
    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#",
    "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.",
    "D": "###../#..#./#...#/#...#/#...#/#..#./###..",
    "E": "#####/#..../#..../####./#..../#..../#####",
    "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.####",
    "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.",
    "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",
    "N": "#...#/#...#/##..#/#.#.#/#..##/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.",
    "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#",
    "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..",
    "Z": "#####/....#/...#./..#../.#.../#..../#####",
    "[": ".###./.#.../.#.../.#.../.#.../.#.../.###.",
    "\\": "#..../.#.../..#../...#./....#/...../.....",
    "]": ".###./...#./...#./...#./...#./...#./.###.",
    "^": "..#../.#.#./#...#/...../...../...../.....",
    "_": "...../...../...../...../...../...../#####",
    "`": ".#.../..#../...../...../...../...../.....",
    "a": "...../...../.###./....#/.####/#...#/.####",
    "b": "#..../#..../####./#...#/#...#/#...#/####.",
    "c": "...../...../.###./#..../#..../#...#/.###.",
    "d": "....#/....#/.####/#...#/#...#/#...#/.####",
    "e": "...../...../.###./#...#/#####/#..../.###.",
    "f": "..##./.#..#/.#.../###../.#.../.#.../.#...",
    "g": "...../...../.####/#...#/.####/....#/####.",
    "h": "#..../#..../####./#...#/#...#/#...#/#...#",
    "i": "..#../...../.##../..#../..#../..#../.###.",
    "j": "...#./...../...#./...#./...#./#..#./.##..",
    "k": "#..../#..../#..#./#.#../##.../#.#../#..#.",
    "l": ".##../..#../..#../..#../..#../..#../.###.",
    "m": "...../...../##.#./#.#.#/#.#.#/#.#.#/#.#.#",
    "n": "...../...../####./#...#/#...#/#...#/#...#",
    "o": "...../...../.###./#...#/#...#/#...#/.###.",
    "p": "...../...../####./#...#/####./#..../#....",
    "q": "...../...../.####/#...#/.####/....#/....#",
    "r": "...../...../#.##./##..#/#..../#..../#....",
    "s": "...../...../.####/#..../.###./....#/####.",
    "t": ".#.../.#.../###../.#.../.#.../.#..#/..##.",
    "u": "...../...../#...#/#...#/#...#/#..##/.##.#",
    "v": "...../...../#...#/#...#/#...#/.#.#./..#..",
    "w": "...../...../#...#/#.#.#/#.#.#/#.#.#/.#.#.",
    "x": "...../...../#...#/.#.#./..#../.#.#./#...#",
    "y": "...../...../#...#/#...#/.####/....#/.###.",
    "z": "...../...../#####/...#./..#../.#.../#####",
    "{": "..##./..#../..#../##.../..#../..#../..##.",
    "|": "..#../..#../..#../..#../..#../..#../..#..",
    "}": ".##../..#../..#../...##/..#../..#../.##..",
    "~": "...../...../.##.#/#..#./...../...../.....",
}

# --- 3x5: for dense rows (todo lists, multi-line agendas). ------------------
# Uppercase, digits and light punctuation only; lowercase maps to uppercase.
FONT_3X5_GLYPHS: dict[str, str] = {
    " ": ".../.../.../.../...",
    "!": ".#./.#./.#./.../.#.",
    "'": ".#./.#./.../.../...",
    "(": "..#/.#./.#./.#./..#",
    ")": "#../.#./.#./.#./#..",
    "+": ".../.#./###/.#./...",
    ",": ".../.../.../.#./#..",
    "-": ".../.../###/.../...",
    ".": ".../.../.../.../.#.",
    "/": "..#/..#/.#./#../#..",
    "0": "###/#.#/#.#/#.#/###",
    "1": ".#./##./.#./.#./###",
    "2": "###/..#/###/#../###",
    "3": "###/..#/.##/..#/###",
    "4": "#.#/#.#/###/..#/..#",
    "5": "###/#../###/..#/###",
    "6": "###/#../###/#.#/###",
    "7": "###/..#/..#/..#/..#",
    "8": "###/#.#/###/#.#/###",
    "9": "###/#.#/###/..#/###",
    ":": ".../.#./.../.#./...",
    "?": "###/..#/.##/.../.#.",
    "A": "###/#.#/###/#.#/#.#",
    "B": "##./#.#/##./#.#/##.",
    "C": "###/#../#../#../###",
    "D": "##./#.#/#.#/#.#/##.",
    "E": "###/#../##./#../###",
    "F": "###/#../##./#../#..",
    "G": "###/#../#.#/#.#/###",
    "H": "#.#/#.#/###/#.#/#.#",
    "I": "###/.#./.#./.#./###",
    "J": "..#/..#/..#/#.#/###",
    "K": "#.#/#.#/##./#.#/#.#",
    "L": "#../#../#../#../###",
    "M": "#.#/###/###/#.#/#.#",
    "N": "##./#.#/#.#/#.#/#.#",
    "O": "###/#.#/#.#/#.#/###",
    "P": "###/#.#/###/#../#..",
    "Q": "###/#.#/#.#/###/..#",
    "R": "###/#.#/##./#.#/#.#",
    "S": "###/#../###/..#/###",
    "T": "###/.#./.#./.#./.#.",
    "U": "#.#/#.#/#.#/#.#/###",
    "V": "#.#/#.#/#.#/#.#/.#.",
    "W": "#.#/#.#/###/###/#.#",
    "X": "#.#/#.#/.#./#.#/#.#",
    "Y": "#.#/#.#/.#./.#./.#.",
    "Z": "###/..#/.#./#../###",
}

# Ellipsis is drawn as three baseline dots so truncation reads as truncation.
FONT_5X7_GLYPHS["…"] = "...../...../...../...../...../...../#.#.#"
FONT_3X5_GLYPHS["…"] = ".../.../.../.../#.#"


# Real calendars are full of typographic punctuation -- Google Calendar turns
# a typed apostrophe into U+2019 -- and none of it exists in a 5x7 ASCII font.
# Mapping it down beats rendering "It?s probably that time".
TRANSLITERATE = {
    "\u2018": "'", "\u2019": "'", "\u201a": ",", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2013": "-", "\u2014": "-", "\u2010": "-", "\u2011": "-", "\u2212": "-",
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u200b": "",
    "\u2022": "*", "\u00b7": ".", "\u2192": ">", "\u2190": "<",
    "\u00d7": "x", "\u00f7": "/", "\u00b0": "*", "\u20ac": "E",
    "\u00a3": "L", "\u2122": "tm", "\u00ae": "(R)", "\u00a9": "(C)",
}


def to_ascii(text: str) -> str:
    """Fold text onto what a 5x7 ASCII font can actually draw.

    Known punctuation is mapped explicitly; accented letters are stripped to
    their base form (so "Renée" draws as "Renee" rather than "Ren??").
    """
    import unicodedata

    out = []
    for ch in text:
        if ch in TRANSLITERATE:
            out.append(TRANSLITERATE[ch])
        elif ord(ch) < 128:
            out.append(ch)
        else:
            folded = unicodedata.normalize("NFKD", ch)
            stripped = "".join(c for c in folded if not unicodedata.combining(c))
            out.append(stripped if stripped.isascii() else ch)
    return "".join(out)


@dataclass(frozen=True)
class Glyph:
    """One character, already trimmed to its inked columns."""

    rows: tuple[str, ...]
    width: int


@dataclass
class BitmapFont:
    """A fixed-cell pixel font, optionally rendered proportionally.

    Proportional mode trims blank columns off each glyph before drawing, which
    buys back a surprising amount of room on a 192px canvas -- "1" and "i" stop
    reserving five columns each.
    """

    name: str
    source: dict[str, str]
    cell_width: int
    height: int
    tracking: int = 1
    space_width: int = 2
    proportional: bool = True
    uppercase_only: bool = False
    fallback: str = "?"
    _cache: dict[str, Glyph] = field(default_factory=dict, repr=False)

    def _normalize(self, ch: str) -> str:
        if self.uppercase_only:
            ch = ch.upper()
        if ch not in self.source:
            ch = self.fallback if self.fallback in self.source else " "
        return ch

    def glyph(self, ch: str) -> Glyph:
        ch = self._normalize(ch)
        cached = self._cache.get(ch)
        if cached is not None:
            return cached

        rows = tuple(self.source[ch].split("/"))
        if len(rows) != self.height:
            raise ValueError(
                f"font {self.name!r} glyph {ch!r} has {len(rows)} rows, expected {self.height}"
            )

        inked = [x for x in range(self.cell_width) if any(r[x] == "#" for r in rows)]
        if not inked:
            # Blank glyph (space): keep a deliberate width, no pixels.
            glyph = Glyph(rows=tuple("" for _ in rows), width=self.space_width)
        elif self.proportional:
            lo, hi = inked[0], inked[-1] + 1
            glyph = Glyph(rows=tuple(r[lo:hi] for r in rows), width=hi - lo)
        else:
            glyph = Glyph(rows=rows, width=self.cell_width)

        self._cache[ch] = glyph
        return glyph

    def advance(self, ch: str) -> int:
        return self.glyph(ch).width + self.tracking

    def measure(self, text: str) -> int:
        """Width in pixels, excluding the trailing tracking gap."""
        text = to_ascii(text)
        if not text:
            return 0
        return sum(self.advance(c) for c in text) - self.tracking

    def mask(self, text: str) -> Image.Image:
        """A 1-bit mask of the text, sized exactly to the inked extent."""
        text = to_ascii(text)
        width = max(self.measure(text), 1)
        img = Image.new("1", (width, self.height), 0)
        if not text:
            return img
        px = img.load()
        x = 0
        for ch in text:
            glyph = self.glyph(ch)
            for y, row in enumerate(glyph.rows):
                for dx, cell in enumerate(row):
                    if cell == "#":
                        px[x + dx, y] = 1
            x += glyph.width + self.tracking
        return img

    def truncate(self, text: str, max_width: int, marker: str = "…") -> str:
        """Shorten text to fit, appending an ellipsis when anything is dropped."""
        text = to_ascii(text)
        if self.measure(text) <= max_width:
            return text
        marker_w = self.measure(marker)
        if marker_w > max_width:
            return ""
        budget = max_width - marker_w - self.tracking
        out: list[str] = []
        used = 0
        for ch in text:
            step = self.advance(ch)
            if used + self.glyph(ch).width > budget:
                break
            out.append(ch)
            used += step
        return "".join(out).rstrip() + marker

    def wrap(self, text: str, max_width: int) -> list[str]:
        """Greedy word wrap; words longer than a line are hard-split."""
        lines: list[str] = []
        current = ""
        for word in to_ascii(text).split():
            candidate = f"{current} {word}" if current else word
            if self.measure(candidate) <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            while self.measure(word) > max_width:
                cut = len(word)
                while cut > 1 and self.measure(word[:cut]) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
        return lines


FONT_5X7 = BitmapFont("5x7", FONT_5X7_GLYPHS, cell_width=5, height=7, space_width=2)
FONT_3X5 = BitmapFont(
    "3x5", FONT_3X5_GLYPHS, cell_width=3, height=5, space_width=1, uppercase_only=True
)
# Monospaced variants keep columns aligned -- use for clocks and countdowns,
# where proportional digits make the display twitch every second.
FONT_5X7_MONO = BitmapFont(
    "5x7mono", FONT_5X7_GLYPHS, cell_width=5, height=7, space_width=5, proportional=False
)

FONTS: dict[str, BitmapFont] = {f.name: f for f in (FONT_5X7, FONT_3X5, FONT_5X7_MONO)}


@lru_cache(maxsize=None)
def get_font(name: str) -> BitmapFont:
    try:
        return FONTS[name]
    except KeyError:
        raise KeyError(f"unknown font {name!r}; available: {sorted(FONTS)}") from None
