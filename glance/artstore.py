"""Managing the files in assets/static/ over HTTP.

Adding artwork was the last thing that still needed a redeploy. Config has
been live-editable for a while; this closes the loop.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .canvas import MAX_PANEL_WIDTH, PANEL_HEIGHT

ALLOWED_SUFFIXES = {".png", ".gif", ".bmp", ".webp"}
MAX_BYTES = 4 * 1024 * 1024
# Deliberately strict: the name becomes a path, and anything outside this set
# is a chance to escape the directory or collide with a shell.
SAFE_STEM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class ArtError(ValueError):
    """Something about the upload is wrong, with a message worth showing."""


@dataclass
class ArtFile:
    name: str
    filename: str
    width: int
    height: int
    bytes: int
    fits: bool


def safe_name(raw: str) -> str:
    """Reduce an uploaded filename to something that cannot escape the dir."""
    candidate = Path(str(raw or "")).name          # strip any directory part
    stem, dot, suffix = candidate.rpartition(".")
    if not dot:
        raise ArtError("the file needs an extension")
    suffix = "." + suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ArtError(f"{suffix} is not an image type this panel can use")
    stem = stem.strip().replace(" ", "-")
    if not SAFE_STEM.match(stem):
        raise ArtError("name must be letters, digits, dot, dash or underscore")
    return stem + suffix


def inspect(data: bytes) -> tuple[int, int]:
    """Confirm it really is an image, and get its size."""
    try:
        image = Image.open(io.BytesIO(data))
        image.verify()
        return Image.open(io.BytesIO(data)).size
    except Exception as exc:  # noqa: BLE001
        raise ArtError("that file is not a readable image") from exc


def save(static_dir: Path, filename: str, data: bytes,
         panel_width: int = 192) -> ArtFile:
    if not data:
        raise ArtError("the file is empty")
    if len(data) > MAX_BYTES:
        raise ArtError(f"too large ({len(data) // 1024} KB, limit is {MAX_BYTES // 1024} KB)")

    name = safe_name(filename)
    width, height = inspect(data)
    if width > MAX_PANEL_WIDTH * 8 or height > PANEL_HEIGHT * 8:
        raise ArtError(f"{width}x{height} is far larger than the panel; export smaller")

    static_dir = Path(static_dir)
    static_dir.mkdir(parents=True, exist_ok=True)
    target = static_dir / name
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)          # atomic, so a half-written file is never served

    return ArtFile(
        name=target.stem, filename=name, width=width, height=height,
        bytes=len(data), fits=(width == panel_width and height == PANEL_HEIGHT),
    )


def listing(static_dir: Path, panel_width: int = 192) -> list[ArtFile]:
    static_dir = Path(static_dir)
    if not static_dir.is_dir():
        return []
    out: list[ArtFile] = []
    for path in sorted(static_dir.iterdir()):
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        try:
            with Image.open(path) as image:
                width, height = image.size
        except Exception:  # noqa: BLE001 - a broken file should still be listed
            width = height = 0
        out.append(ArtFile(
            name=path.stem, filename=path.name, width=width, height=height,
            bytes=path.stat().st_size,
            fits=(width == panel_width and height == PANEL_HEIGHT),
        ))
    return out


def delete(static_dir: Path, name: str) -> bool:
    """Remove one file. The name is sanitised the same way it was on the way
    in, so a crafted name cannot reach outside the directory."""
    static_dir = Path(static_dir).resolve()
    candidate = Path(str(name or "")).name
    for suffix in ("",) + tuple(ALLOWED_SUFFIXES):
        target = (static_dir / f"{candidate}{suffix}").resolve()
        if static_dir not in target.parents:
            continue                    # refuses ../ and absolute paths
        if target.is_file() and target.suffix.lower() in ALLOWED_SUFFIXES:
            target.unlink()
            return True
    return False
