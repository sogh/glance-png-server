"""Deciding which scene a channel serves on any given fetch.

The device hits one URL on a fixed interval and displays whatever comes back,
so the rotation lives entirely here. Two policies:

  advance  Each real fetch moves to the next available scene. Rotation tracks
           the *scene key*, not an index, so reordering a channel in config
           does not make the sequence jump.
  clock    The scene is a pure function of wall-clock time. Stateless and
           identical across restarts and replicas, at the cost of skipping
           entries when the refresh interval and dwell time do not line up.

Either way, entries that report themselves unavailable are skipped, so an
empty todo list silently drops out instead of serving a blank panel.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ChannelEntry, Settings
from .scenes.base import RenderContext, Scene, resolve

WEEKDAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _wanted(value: Any) -> set[str]:
    if isinstance(value, str):
        return {v.strip() for v in value.split(",") if v.strip()}
    return {str(v).strip() for v in value if str(v).strip()}


def matches_when(when: dict[str, Any], now: datetime,
                 modes: frozenset[str] = frozenset()) -> bool:
    """Evaluate a channel entry's optional condition.

    Supported keys: months, weekdays, hours (list or {from,to}), dates
    ("MM-DD"), from/to ("HH:MM"), mode, not_mode. An empty condition always
    matches.
    """
    if not when:
        return True

    # `mode` is any-of, `not_mode` is none-of, so a single entry can say "while
    # visitors are here" or "any time they are not".
    if "mode" in when and not (_wanted(when["mode"]) & set(modes)):
        return False
    if "not_mode" in when and (_wanted(when["not_mode"]) & set(modes)):
        return False

    if "months" in when and now.month not in [int(m) for m in when["months"]]:
        return False

    if "weekdays" in when:
        wanted = {
            WEEKDAY_NAMES[str(d)[:3].lower()] if isinstance(d, str) else int(d)
            for d in when["weekdays"]
        }
        if now.weekday() not in wanted:
            return False

    if "dates" in when:
        stamp = now.strftime("%m-%d")
        if stamp not in {str(d).replace("/", "-") for d in when["dates"]}:
            return False

    hours = when.get("hours")
    if isinstance(hours, dict):
        lo, hi = int(hours.get("from", 0)), int(hours.get("to", 23))
        # A window like {from: 22, to: 6} is understood as wrapping midnight.
        inside = lo <= now.hour <= hi if lo <= hi else (now.hour >= lo or now.hour <= hi)
        if not inside:
            return False
    elif hours is not None and now.hour not in [int(h) for h in hours]:
        return False

    minutes = now.hour * 60 + now.minute
    if "from" in when:
        h, m = (int(x) for x in str(when["from"]).split(":"))
        if minutes < h * 60 + m:
            return False
    if "to" in when:
        h, m = (int(x) for x in str(when["to"]).split(":"))
        if minutes > h * 60 + m:
            return False
    return True


@dataclass
class Selection:
    entry: ChannelEntry
    scene: Scene
    params: dict[str, Any]
    takeover: bool = False
    position: int = 0
    total: int = 1

    @property
    def key(self) -> str:
        return self.entry.key


class Carousel:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state_file = Path(settings.state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._state = self._read_state()
        # Guards against a double-fetch (a device retry, a browser preload, a
        # health check) burning two slots in one refresh cycle. The device's
        # own minimum refresh is 60s, so anything comfortably under that is
        # safe while still absorbing a burst.
        self.min_advance_interval = settings.carousel_min_advance

    # --- persistence -------------------------------------------------------

    def _read_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_state(self) -> None:
        tmp = self.state_file.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(self._state, indent=2))
            tmp.replace(self.state_file)
        except OSError:
            pass  # rotation surviving a restart is a nicety, not a requirement

    def state_for(self, channel: str) -> dict[str, Any]:
        return dict(self._state.get(channel, {}))

    def reset(self, channel: str | None = None) -> None:
        with self._lock:
            if channel is None:
                self._state = {}
            else:
                self._state.pop(channel, None)
            self._write_state()

    # --- selection ---------------------------------------------------------

    def candidates(self, channel: str, ctx: RenderContext) -> list[Selection]:
        """Entries that are enabled, in their time window, and have content."""
        out: list[Selection] = []
        for entry in self.settings.channels.get(channel, []):
            # ctx.modes costs a calendar parse, so only ask when an entry
            # actually mentions one.
            if not entry.enabled:
                continue
            needs_modes = "mode" in entry.when or "not_mode" in entry.when
            if not matches_when(entry.when, ctx.now,
                                ctx.modes if needs_modes else frozenset()):
                continue
            scene, params = resolve(entry.ref, entry.params)
            if scene is None:
                continue
            try:
                if not scene.available(ctx, params):
                    continue
            except Exception:  # noqa: BLE001 - a broken source must not stall the whole channel
                continue
            out.append(Selection(entry=entry, scene=scene, params=params,
                                 takeover=entry.takeover))
        return out

    def select(self, channel: str, ctx: RenderContext, advance: bool = True) -> Selection | None:
        available = self.candidates(channel, ctx)
        if not available:
            return None

        # A takeover entry (Christmas morning, a fire alarm) pre-empts the
        # rotation without disturbing where the rotation had got to.
        for sel in available:
            if sel.takeover:
                sel.position, sel.total = 0, len(available)
                return sel

        if self.settings.carousel_mode == "clock":
            dwell = max(1, self.settings.carousel_dwell)
            index = int(time.time() // dwell) % len(available)
        else:
            index = self._advance_index(channel, available, advance)

        chosen = available[index]
        chosen.position, chosen.total = index, len(available)
        return chosen

    def _advance_index(self, channel: str, available: list[Selection], advance: bool) -> int:
        keys = [s.key for s in available]
        with self._lock:
            entry = self._state.get(channel, {})
            last_key = entry.get("last_key")
            last_at = float(entry.get("last_at", 0))
            now = time.time()

            if last_key not in keys:
                index = 0                      # first run, or the last scene dried up
            else:
                current = keys.index(last_key)
                # How long this entry has earned. The double-fetch debounce is
                # the floor; a per-entry `dwell` extends it, which is the only
                # way to control pace -- the device's refresh interval is not
                # ours to set, so "show this one for five minutes" has to mean
                # "keep returning it until five minutes have passed".
                hold_for = max(self.min_advance_interval, available[current].entry.dwell)
                if not advance or (now - last_at) < hold_for:
                    index = current
                else:
                    index = (current + 1) % len(keys)

            if advance:
                self._state[channel] = {
                    "last_key": keys[index],
                    "last_at": now,
                    "count": int(entry.get("count", 0)) + 1,
                }
                self._write_state()
            return index
