"""Multi-frame output, encoded as APNG.

Whether the panel animates this is an open question -- the docs say PNG and
say nothing about APNG, and small embedded decoders usually ignore the
animation chunks. The reason it is worth trying anyway is that **an APNG is a
valid PNG**: `acTL`, `fcTL` and `fdAT` are ancillary chunks, and the first
frame lives in a perfectly ordinary `IDAT`. A decoder that understands them
animates; one that does not renders frame 0 and is none the wiser.

So the downside of sending one is a static image, which is what you had.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image

from .canvas import Canvas


@dataclass
class Frames:
    """An ordered set of canvases, encoded as a single animated PNG."""

    canvases: list[Canvas] = field(default_factory=list)
    duration: int = 100          # milliseconds per frame
    loop: int = 0                # 0 = loop forever

    def __post_init__(self) -> None:
        if not self.canvases:
            raise ValueError("Frames needs at least one canvas")
        first = self.canvases[0]
        for c in self.canvases[1:]:
            if c.image.size != first.image.size:
                raise ValueError("every frame must be the same size")

    def __len__(self) -> int:
        return len(self.canvases)

    @property
    def width(self) -> int:
        return self.canvases[0].width

    @property
    def height(self) -> int:
        return self.canvases[0].height

    def to_png(self, quantize: bool = True) -> bytes:
        """Encode to APNG bytes.

        Frames stay in RGB rather than being palette-quantized: a shared
        palette across frames is fiddly and buys little here, where a whole
        animation is typically a couple of KB against a 1 MB cap.
        """
        if len(self.canvases) == 1:
            return self.canvases[0].to_png(quantize=quantize)

        buf = io.BytesIO()
        images = [c.image for c in self.canvases]
        images[0].save(
            buf,
            format="PNG",
            save_all=True,
            append_images=images[1:],
            duration=self.duration,
            loop=self.loop,
            optimize=True,
        )
        return buf.getvalue()

    def first(self) -> Canvas:
        """The frame a non-animating decoder will show."""
        return self.canvases[0]


def marquee_frames(
    width: int,
    text: str,
    color: str = "amber",
    font: str = "5x7",
    y: int | None = None,
    step: int = 2,
    gap: int | None = None,
    duration: int = 80,
    max_frames: int = 160,
    background: str = "black",
    scale: int = 1,
) -> Frames:
    """Text scrolling right-to-left, looping seamlessly.

    The loop closes by drawing the string twice, one full period apart, so the
    tail of one pass is already entering as the head of the last one leaves.
    """
    from .fonts import get_font

    f = get_font(font)
    text_w = f.measure(text) * scale
    gap = width // 2 if gap is None else gap
    period = max(1, text_w + gap)
    step = max(1, step)

    # A whole loop is period/step frames; clamp so a long string cannot
    # produce a needlessly enormous file.
    count = min(max(1, -(-period // step)), max_frames)
    top = (32 - f.height * scale) // 2 if y is None else y

    canvases = []
    for i in range(count):
        c = Canvas(width=width)
        c.clear(background)
        offset = (i * step) % period
        c.text(-offset, top, text, color, f, scale=scale)
        c.text(-offset + period, top, text, color, f, scale=scale)
        canvases.append(c)
    return Frames(canvases=canvases, duration=duration)
