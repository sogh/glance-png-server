#!/usr/bin/env python3
"""Generate docs/SCENES.md from the scene registry.

Written rather than hand-maintained because a hand-maintained list of 27
scenes and 163 parameters is a list that is wrong within a month. The param
schema already exists -- it is what draws the controls in /edit and what
validates a save -- so the reference may as well come from the same place.

    python tools/gendocs.py            write docs/SCENES.md
    python tools/gendocs.py --check    exit 1 if it is out of date

A test runs --check, so a new scene or a renamed parameter fails the suite
until the docs catch up.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from glance.scenes import REGISTRY  # noqa: E402
from glance.scenes.base import COMMON_PARAMS  # noqa: E402

TARGET = ROOT / "docs" / "SCENES.md"

# What an "@marker" stands for, since the generated doc cannot resolve one.
MARKERS = {
    "@colors": "any palette colour or `#rrggbb`",
    "@fonts": "`5x7`, `3x5`, `5x7mono`",
    "@sprites": "any sprite in `glance/sprites.py`",
    "@calendars": "a calendar named under `sources.calendars`",
    "@static": "a PNG in `assets/static/`",
    "@scenes": "any scene id in this file",
    "@entities": "a Home Assistant entity id",
    "@boards": "a board named under `sources.scoreboards`",
    "@languages": "a deck in `config/vocabulary/`",
}

HEADER = """# Scene reference

Every built-in scene and every parameter it takes. **Generated** by
`tools/gendocs.py` from the scene registry — edit the `Param(...)` declarations
in `glance/scenes/*.py`, not this file, then run:

```bash
python tools/gendocs.py
```

A test fails if this file drifts from the code.

Each scene is used the same way, in a channel:

```yaml
channels:
  main:
    - scene: <id>
      params: { ... }
      takeover: false       # pre-empt the rotation while available
      when: {}              # months, weekdays, hours, dates, from/to, mode
      dwell: 0              # seconds to hold before advancing
      enabled: true
```

You can also render one directly, which is how the preview page does it:

```
/s/<id>.png?param=value
```

## Every scene accepts

| Param | Type | Default | Means |
|---|---|---|---|
"""


def cell(value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    return f"`{value}`"


def options_of(param) -> str:
    if isinstance(param.options, str):
        return MARKERS.get(param.options, param.options)
    if isinstance(param.options, list):
        return ", ".join(f"`{o}`" for o in param.options)
    if param.type == "color":
        return MARKERS["@colors"]
    return ""


def describe(param) -> str:
    bits = []
    if param.help:
        text = param.help.strip()
        # The help strings are written to sit under a form control, so most
        # carry no full stop. One is needed here, before the options list.
        bits.append(text if text[-1] in ".!?" else text + ".")
    opts = options_of(param)
    if opts and param.type in ("select", "color"):
        bits.append(f"One of: {opts}.")
    limits = []
    if param.minimum is not None:
        limits.append(f"min {param.minimum:g}")
    if param.maximum is not None:
        limits.append(f"max {param.maximum:g}")
    if limits:
        bits.append(f"({', '.join(limits)})")
    return " ".join(bits) or "—"


def row(param) -> str:
    return (f"| `{param.name}` | {param.type} | {cell(param.default)} "
            f"| {describe(param)} |\n")


def render() -> str:
    out = [HEADER]
    for param in COMMON_PARAMS:
        out.append(row(param))

    out.append("\n## Scenes\n\n")
    out.append("| Scene | Shows |\n|---|---|\n")
    for sid in sorted(REGISTRY):
        scene = REGISTRY[sid]
        out.append(f"| [`{sid}`](#{sid.replace(':', '')}) "
                   f"| {getattr(scene, 'description', '') or '—'} |\n")

    for sid in sorted(REGISTRY):
        scene = REGISTRY[sid]
        out.append(f"\n### `{sid}`\n\n")
        description = getattr(scene, "description", "")
        if description:
            out.append(f"{description}\n\n")
        params = [p for p in getattr(scene, "params", [])]
        if not params:
            out.append("Takes no parameters of its own.\n")
            continue
        out.append("| Param | Type | Default | Means |\n|---|---|---|---|\n")
        for param in params:
            out.append(row(param))
    return "".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the file is out of date")
    args = parser.parse_args()

    fresh = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current == fresh:
            print(f"{TARGET.relative_to(ROOT)} is current")
            return 0
        print(f"{TARGET.relative_to(ROOT)} is out of date -- "
              f"run: python tools/gendocs.py", file=sys.stderr)
        return 1

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(fresh, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)} "
          f"({len(REGISTRY)} scenes, "
          f"{sum(len(getattr(s, 'params', [])) for s in REGISTRY.values())} params)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
