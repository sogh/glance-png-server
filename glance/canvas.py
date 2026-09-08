"""The drawing surface: a fixed-height RGB pixel grid that encodes to PNG.

Everything is nearest-neighbour and hard-edged on purpose. No anti-aliasing,
no smooth scaling -- on a 32px panel those only ever produce mud.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

from PIL import Image

from .fonts import BitmapFont, get_font
from .palette import RGB, parse, snap

PANEL_HEIGHT = 32
PANEL_MODULE_WIDTH = 64
MAX_PANEL_WIDTH = 384

HAlign = Literal["left", "center", "right"]
VAlign = Literal["top", "middle", "bottom"]


@dataclass
class Canvas:
    width: int = 192
    height: int = PANEL_HEIGHT
    background: RGB = (0, 0, 0)

    def __post_init__(self) -> None:
        if self.height != PANEL_HEIGHT:
            raise ValueError(f"Glance panels are always {PANEL_HEIGHT}px tall")
        if not 1 <= self.width <= MAX_PANEL_WIDTH:
            raise ValueError(f"width must be 1..{MAX_PANEL_WIDTH}, got {self.width}")
        self.image = Image.new("RGB", (self.width, self.height), snap(self.background))

    # --- primitives --------------------------------------------------------

    def clear(self, color: str | RGB | None = None) -> None:
        fill = snap(parse(color)) if color is not None else snap(self.background)
        self.image.paste(fill, (0, 0, self.width, self.height))

    def pixel(self, x: int, y: int, color: str | RGB) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.image.putpixel((x, y), snap(parse(color)))

    def fill_rect(self, x: int, y: int, w: int, h: int, color: str | RGB) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.width, x + w), min(self.height, y + h)
        if x1 > x0 and y1 > y0:
            self.image.paste(snap(parse(color)), (x0, y0, x1, y1))

    def rect(self, x: int, y: int, w: int, h: int, color: str | RGB) -> None:
        """A 1px outline. Drawn as four fills so corners never double-blend."""
        self.fill_rect(x, y, w, 1, color)
        self.fill_rect(x, y + h - 1, w, 1, color)
        self.fill_rect(x, y, 1, h, color)
        self.fill_rect(x + w - 1, y, 1, h, color)

    def hline(self, x: int, y: int, w: int, color: str | RGB) -> None:
        self.fill_rect(x, y, w, 1, color)

    def vline(self, x: int, y: int, h: int, color: str | RGB) -> None:
        self.fill_rect(x, y, 1, h, color)

    # --- text --------------------------------------------------------------

    def text(
        self,
        x: int,
        y: int,
        content: str,
        color: str | RGB = "white",
        font: BitmapFont | str = "5x7",
        align: HAlign = "left",
        max_width: int | None = None,
        scale: int = 1,
    ) -> int:
        """Draw one line of bitmap text. Returns the width actually drawn.

        `x` is the anchor: the left edge for align='left', the centre for
        'center', the right edge for 'right'.

        `scale` multiplies the glyphs by a whole number of pixels -- the only
        way to enlarge type here that keeps every edge on a pixel boundary. A
        scale of 2 turns the 5x7 into a chunky 10x14 suitable for a hero clock.
        """
        f = get_font(font) if isinstance(font, str) else font
        scale = max(1, int(scale))
        if max_width is not None:
            content = f.truncate(content, max_width // scale)
        if not content:
            return 0

        w = f.measure(content) * scale
        left = x if align == "left" else x - w // 2 if align == "center" else x - w
        mask = f.mask(content)
        if scale > 1:
            mask = mask.resize((mask.width * scale, mask.height * scale), Image.Resampling.NEAREST)
        self.image.paste(snap(parse(color)), (left, y), mask)
        return w

    def text_block(
        self,
        x: int,
        y: int,
        lines: list[str],
        color: str | RGB = "white",
        font: BitmapFont | str = "5x7",
        align: HAlign = "left",
        leading: int = 1,
        max_width: int | None = None,
        scale: int = 1,
    ) -> int:
        """Stack several lines. Returns total height consumed."""
        f = get_font(font) if isinstance(font, str) else font
        scale = max(1, int(scale))
        step = f.height * scale + leading
        for i, line in enumerate(lines):
            self.text(x, y + i * step, line, color, f, align, max_width, scale)
        return max(0, len(lines) * step - leading)

    def centered(
        self,
        content: str,
        color: str | RGB = "white",
        font: BitmapFont | str = "5x7",
        y: int | None = None,
        max_width: int | None = None,
        scale: int = 1,
    ) -> int:
        """Horizontally and (by default) vertically centred single line."""
        f = get_font(font) if isinstance(font, str) else font
        scale = max(1, int(scale))
        top = (self.height - f.height * scale) // 2 if y is None else y
        return self.text(
            self.width // 2, top, content, color, f, "center",
            self.width - 2 if max_width is None else max_width, scale,
        )

    # --- images ------------------------------------------------------------

    def blit(self, img: Image.Image, x: int = 0, y: int = 0) -> None:
        """Paste an image, honouring alpha, with no resampling."""
        src = img.convert("RGBA")
        self.image.paste(src.convert("RGB"), (x, y), src.split()[-1])

    def fit(self, img: Image.Image, align: HAlign = "center", valign: VAlign = "middle") -> None:
        """Place an arbitrary image on the panel without smoothing it.

        Oversized art is downscaled nearest-neighbour (blocky, but honest --
        a bilinear shrink to 32px produces grey soup on LEDs). Undersized art
        is positioned, never stretched.
        """
        src = img.convert("RGBA")
        if src.width > self.width or src.height > self.height:
            scale = min(self.width / src.width, self.height / src.height)
            new = (max(1, int(src.width * scale)), max(1, int(src.height * scale)))
            src = src.resize(new, Image.Resampling.NEAREST)

        x = 0 if align == "left" else self.width - src.width if align == "right" else (self.width - src.width) // 2
        y = 0 if valign == "top" else self.height - src.height if valign == "bottom" else (self.height - src.height) // 2
        self.image.paste(src.convert("RGB"), (x, y), src.split()[-1])

    # --- output ------------------------------------------------------------

    def to_png(self, quantize: bool = True) -> bytes:
        """Encode to PNG bytes.

        Quantizing to a palette typically cuts these files to a couple of KB.
        Well under the 1 MB response cap either way, but a smaller body means a
        faster fetch inside the device's ~4s request timeout.
        """
        out = self.image
        if quantize:
            colors = out.getcolors(maxcolors=256)
            if colors is not None:
                out = out.convert("P", palette=Image.Palette.ADAPTIVE, colors=max(2, len(colors)))
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True, compress_level=9)
        return buf.getvalue()

    def scaled(self, factor: int = 4) -> Image.Image:
        """A blown-up copy for previewing on a normal screen."""
        return self.image.resize(
            (self.width * factor, self.height * factor), Image.Resampling.NEAREST
        )

    def to_ascii(self) -> str:
        """Terminal preview -- useful in tests and when iterating over SSH."""
        rows = []
        for y in range(self.height):
            rows.append(
                "".join(
                    "#" if sum(self.image.getpixel((x, y))) > 90 else "."
                    for x in range(self.width)
                )
            )
        return "\n".join(rows)
