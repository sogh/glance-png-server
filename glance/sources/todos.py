"""TODOs read from a local JSON file.

The file is re-read whenever its mtime changes, so anything that writes it --
a script, a shortcut, your editor -- shows up on the panel at the next refresh
with no restart.

Schema (data/todos.json):
    [
      {"text": "Renew passport", "due": "2026-09-14", "priority": 1, "done": false},
      {"text": "Buy cat food"}
    ]
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


@dataclass
class Todo:
    text: str
    due: date | None = None
    priority: int = 3          # 1 = highest
    done: bool = False
    tag: str = ""

    def days_until(self, today: date) -> int | None:
        return None if self.due is None else (self.due - today).days

    def is_overdue(self, today: date) -> bool:
        return self.due is not None and self.due < today


def _parse_due(value: object) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class TodoSource:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.last_error: str | None = None
        self._lock = threading.Lock()
        self._mtime: float | None = None
        self._cached: list[Todo] = []

    def _load(self) -> list[Todo]:
        raw = json.loads(self.path.read_text())
        if isinstance(raw, dict):                      # tolerate {"todos": [...]}
            raw = raw.get("todos", [])
        out: list[Todo] = []
        for item in raw:
            if isinstance(item, str):
                out.append(Todo(text=item))
                continue
            out.append(
                Todo(
                    text=str(item.get("text") or item.get("title") or "").strip(),
                    due=_parse_due(item.get("due")),
                    priority=int(item.get("priority", 3)),
                    done=bool(item.get("done", False)),
                    tag=str(item.get("tag", "") or ""),
                )
            )
        return [t for t in out if t.text]

    def all(self) -> list[Todo]:
        with self._lock:
            if not self.path.exists():
                self.last_error = f"{self.path} not found"
                return []
            mtime = self.path.stat().st_mtime
            if mtime != self._mtime:
                try:
                    self._cached = self._load()
                    self.last_error = None
                except Exception as exc:  # noqa: BLE001 - keep the last good list
                    self.last_error = f"{type(exc).__name__}: {exc}"
                else:
                    self._mtime = mtime
            return list(self._cached)

    def open_items(self, today: date, limit: int | None = None) -> list[Todo]:
        """Undone items, most urgent first: overdue, then by due date, then priority."""
        items = [t for t in self.all() if not t.done]
        items.sort(
            key=lambda t: (
                t.due is None,                                   # dated items first
                t.due or date.max,
                t.priority,
                t.text.lower(),
            )
        )
        return items[:limit] if limit else items
