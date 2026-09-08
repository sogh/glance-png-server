"""Scenes backed by PNG files you made by hand (Photoshop, Aseprite, whatever).

Files live in assets/static/. Drop one in and it is immediately addressable as
`static:<filename-without-extension>` from a channel or the /s/ endpoint --
no restart, no registration step.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from PIL import Image

from ..canvas import Canvas
from .base import RenderContext, register

_cache: dict[Path, tuple[float, Image.Image]] = {}
_lock = threading.Lock()

SUFFIXES = (".png", ".gif", ".bmp", ".webp")


def resolve_path(ctx: RenderContext, name: str) -> Path | None:
    """Find an art file by name, with or without an extension."""
    base = ctx.settings.static_dir
    candidate = Path(name)
    if candidate.suffix:
        p = base / candidate
        return p if p.is_file() else None
    for suffix in SUFFIXES:
        p = base / f"{name}{suffix}"
        if p.is_file():
            return p
    return None


def load_image(path: Path) -> Image.Image:
    """Load with an mtime-keyed cache, so re-exporting art hot-reloads it."""
    mtime = path.stat().st_mtime
    with _lock:
        cached = _cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        img = Image.open(path)
        img.load()
        img = img.convert("RGBA")
        _cache[path] = (mtime, img)
        return img


def list_static(ctx: RenderContext) -> list[str]:
    base = ctx.settings.static_dir
    if not base.is_dir():
        return []
    return sorted(p.stem for p in base.iterdir() if p.suffix.lower() in SUFFIXES)


def _available(ctx: RenderContext, params: dict[str, Any]) -> bool:
    name = params.get("name")
    return bool(name) and resolve_path(ctx, str(name)) is not None


@register("static", available=_available, description="A PNG file from assets/static/")
def render_static(ctx: RenderContext, params: dict[str, Any]) -> Canvas:
    name = str(params.get("name", ""))
    path = resolve_path(ctx, name)
    c = ctx.canvas()
    c.clear(params.get("background", "black"))
    if path is None:
        c.centered(f"missing: {name}", "red", "3x5")
        return c

    img = load_image(path)
    c.fit(img, align=params.get("align", "center"), valign=params.get("valign", "middle"))

    # An overlay caption lets one piece of art be reused with different text.
    caption = params.get("caption")
    if caption:
        c.fill_rect(0, c.height - 7, c.width, 7, (0, 0, 0))
        c.text(c.width // 2, c.height - 6, str(caption),
               params.get("caption_color", "white"), "3x5", "center", c.width - 4)
    return c
