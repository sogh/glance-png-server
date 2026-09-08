#!/usr/bin/env python
"""Render scenes from the command line -- to a PNG, or as ASCII in the terminal.

    tools/render.py clock                    # ascii preview
    tools/render.py todos --png out.png      # write a file
    tools/render.py --channel main           # what the device would get next
    tools/render.py --all --dir /tmp/frames  # every scene, for a design pass
    tools/render.py holiday --at 2026-12-25  # pretend it is another day
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glance.runtime import GlanceApp  # noqa: E402
from glance.scenes import REGISTRY  # noqa: E402


def parse_params(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        low = value.lower()
        if low in ("true", "false"):
            out[key] = low == "true"
        else:
            try:
                out[key] = int(value)
            except ValueError:
                out[key] = value
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", nargs="?", help="scene id, e.g. clock or static:winter")
    ap.add_argument("--channel", help="render a channel instead of a single scene")
    ap.add_argument("--config", help="path to settings.yaml")
    ap.add_argument("--png", help="write the PNG here")
    ap.add_argument("--dir", help="with --all, the output directory")
    ap.add_argument("--all", action="store_true", help="render every registered scene")
    ap.add_argument("--at", help="pretend it is this datetime (YYYY-MM-DD[THH:MM])")
    ap.add_argument("--scale", type=int, default=6, help="upscale factor for --png")
    ap.add_argument("-p", "--param", action="append", default=[], metavar="K=V")
    args = ap.parse_args()

    app = GlanceApp.from_config(args.config)
    now = None
    if args.at:
        stamp = args.at if "T" in args.at else f"{args.at}T09:00"
        now = datetime.fromisoformat(stamp).replace(tzinfo=app.settings.tz)
    ctx = app.context(now)

    def emit(canvas, label: str, path: Path | None) -> None:
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            canvas.scaled(args.scale).save(path)
            print(f"{label:24s} -> {path} ({len(app.png(canvas))} bytes as served)")
        else:
            print(f"--- {label} ({len(app.png(canvas))} bytes) ---")
            print(canvas.to_ascii())

    if args.all:
        out_dir = Path(args.dir or "preview-frames")
        for sid in sorted(REGISTRY):
            if sid == "static":
                continue
            canvas, label = app.render_scene(sid, {}, ctx)
            emit(canvas, label, out_dir / f"{sid}.png")
        return 0

    if args.channel:
        canvas, selection, label = app.render_channel(args.channel, advance=False, now=now)
        emit(canvas, f"{args.channel}:{label}", Path(args.png) if args.png else None)
        return 0

    if not args.scene:
        ap.error("give a scene id, --channel, or --all")

    canvas, label = app.render_scene(args.scene, parse_params(args.param), ctx)
    emit(canvas, label, Path(args.png) if args.png else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
