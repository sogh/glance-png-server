"""Style encoded inside calendar entries.

Google's ICS export carries no colour or category information -- the colour
you pick in Google Calendar does not survive the export, and there is no
CATEGORIES property either. The only fields that reliably come through are
SUMMARY, DESCRIPTION and LOCATION, so that is where styling has to live.

Two ways to write it, both editable from a phone:

    "Take the bins out #amber"          a tag in the title
    description: "color: amber"          a key in the description

Tags are stripped from the title before it is drawn, so the panel shows
"Take the bins out". A `#word` that is not a known keyword is left alone --
"#1 priority" stays exactly as typed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..palette import NAMED

# Words that mean something. Anything else after a # is just text.
STYLE_WORDS = {
    "big": {"style": "hero"},
    "hero": {"style": "hero"},
    "quiet": {"dim": True},
    "hide": {"hidden": True},
    "urgent": {"color": "red", "priority": 1},
    "done": {"done": True},
}
KEYWORDS = set(NAMED) | set(STYLE_WORDS)

_TAG = re.compile(r"(?:^|\s)#([A-Za-z][A-Za-z0-9_-]*)")
_KEYVAL = re.compile(r"^\s*([a-z_]+)\s*[:=]\s*(.+?)\s*$", re.I | re.M)

# Only these may be set from a description; anything else is ignored so a
# normal description cannot accidentally restyle an entry.
ALLOWED_KEYS = {"color", "accent", "style", "priority", "icon", "hidden", "dim"}


@dataclass
class Style:
    color: str | None = None
    accent: str | None = None
    style: str | None = None            # e.g. "hero"
    priority: int | None = None
    hidden: bool = False
    dim: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def merged_over(self, base: "Style") -> "Style":
        """This style wins; anything unset falls back to `base`."""
        return Style(
            color=self.color or base.color,
            accent=self.accent or base.accent,
            style=self.style or base.style,
            priority=self.priority if self.priority is not None else base.priority,
            hidden=self.hidden or base.hidden,
            dim=self.dim or base.dim,
            extra={**base.extra, **self.extra},
        )


def _apply(target: dict[str, Any], updates: dict[str, Any]) -> None:
    for k, v in updates.items():
        target.setdefault(k, v)


def parse_tags(title: str) -> tuple[str, dict[str, Any]]:
    """Pull known #tags out of a title. Returns (clean title, style values)."""
    found: dict[str, Any] = {}
    matched: list[str] = []

    for m in _TAG.finditer(title or ""):
        word = m.group(1).lower()
        if word in NAMED:
            found.setdefault("color", word)
            matched.append(m.group(0))
        elif word in STYLE_WORDS:
            _apply(found, STYLE_WORDS[word])
            matched.append(m.group(0))
        # Unknown -- leave it in the title.

    clean = title or ""
    for token in matched:
        clean = clean.replace(token, " ", 1)
    return re.sub(r"\s{2,}", " ", clean).strip(), found


def parse_description(description: str) -> dict[str, Any]:
    """Read `key: value` lines from an event description."""
    found: dict[str, Any] = {}
    for key, raw in _KEYVAL.findall(description or ""):
        key = key.lower()
        if key not in ALLOWED_KEYS:
            continue
        value: Any = raw.strip()
        if key in ("hidden", "dim"):
            value = str(value).lower() in ("1", "true", "yes", "on")
        elif key == "priority":
            try:
                value = int(value)
            except ValueError:
                continue
        found[key] = value
    return found


def style_for(summary: str, description: str = "") -> tuple[str, Style]:
    """Combine title tags and description keys into one Style.

    Title tags win over description keys -- the title is what you edit in a
    hurry on a phone.
    """
    clean, from_title = parse_tags(summary)
    values = {**parse_description(description), **from_title}
    return clean, Style(
        color=values.get("color"),
        accent=values.get("accent"),
        style=values.get("style"),
        priority=values.get("priority"),
        hidden=bool(values.get("hidden", False)),
        dim=bool(values.get("dim", False)),
        extra={k: v for k, v in values.items() if k not in
               ("color", "accent", "style", "priority", "hidden", "dim")},
    )
