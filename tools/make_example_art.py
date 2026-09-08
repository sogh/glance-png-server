#!/usr/bin/env python
"""Generates a placeholder PNG in assets/static/ so the example channel resolves.

Replace it with your own 192x32 export -- this only exists so a fresh clone has
something to show.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glance.canvas import Canvas
from glance.palette import dim

out = Path(__file__).resolve().parent.parent / "assets" / "static"
out.mkdir(parents=True, exist_ok=True)

c = Canvas(192)
c.clear("black")
for x in range(0, 192, 6):
    hue = ["red", "orange", "amber", "green", "teal", "blue", "indigo", "magenta"][(x // 6) % 8]
    c.fill_rect(x, 0, 3, 32, dim(hue, 0.5))
c.fill_rect(20, 9, 152, 15, "black")
c.centered("YOUR ART HERE", "white", "5x7", y=13)
c.image.save(out / "example-stripes.png")
print(f"wrote {out / 'example-stripes.png'}")
