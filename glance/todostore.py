"""Editing data/reminders.json over HTTP.

Reminders were the last piece of user content with no write path: artwork has
one, channels have one, this did not -- the only way to add a line was to SSH
in and edit JSON. `TodoSource` re-reads the file whenever its mtime changes,
so a write here reaches the panel at the next refresh with no restart.

Two rules shape this module.

**Every write is atomic.** A reader that catches a half-written file parses it
as broken, keeps serving the last good list and sets `last_error` -- which
looks from the kitchen exactly like nothing having happened. Writing to a temp
file and replacing it means no reader ever sees a partial list.

**Strict on the way in, lenient on the way out.** Anything arriving from the
API is validated and refused with a message. Anything already in the file is
coerced as far as it will go, because a hand-written entry with a typo in its
date should still be editable rather than locking the whole page.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Any

MAX_TEXT = 120
MAX_TAG = 32
MAX_ITEMS = 200
MIN_PRIORITY, MAX_PRIORITY = 1, 5

# The panel shows one reminder per row at ~26 characters, so anything past a
# line or two is never going to be read off the wall. The cap is generous
# enough not to annoy and small enough to bound the file.
KNOWN = {"id", "text", "title", "due", "priority", "done", "tag"}
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class TodoError(ValueError):
    """Something about the reminder is wrong, with a message worth showing."""


def _clean(raw: object, limit: int, field: str, *, strict: bool) -> str:
    value = _CONTROL.sub(" ", str(raw if raw is not None else "")).strip()
    if len(value) > limit:
        if strict:
            raise TodoError(f"{field} is longer than {limit} characters")
        value = value[:limit]
    return value


def _due(raw: object, *, strict: bool) -> str:
    if raw in (None, ""):
        return ""
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError:
        if strict:
            raise TodoError("due must be a date like 2026-09-17") from None
        return ""


def _priority(raw: object, *, strict: bool) -> int:
    if raw in (None, ""):
        return 3
    try:
        value = int(raw)
    except (TypeError, ValueError):
        if strict:
            raise TodoError("priority must be a whole number") from None
        return 3
    if not MIN_PRIORITY <= value <= MAX_PRIORITY:
        if strict:
            raise TodoError(f"priority must be between {MIN_PRIORITY} and {MAX_PRIORITY}")
        return min(max(value, MIN_PRIORITY), MAX_PRIORITY)
    return value


def normalise(item: object, *, strict: bool = False) -> dict[str, Any]:
    """One stored reminder, with keys in a stable order.

    Keys this module does not recognise are carried through untouched, so a
    file someone hand-wrote keeps whatever else they put in it.
    """
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        raise TodoError("each reminder must be a string or an object")

    text = _clean(item.get("text") or item.get("title"), MAX_TEXT, "text", strict=strict)
    if not text and strict:
        raise TodoError("text cannot be empty")

    out: dict[str, Any] = {
        "id": str(item.get("id") or uuid.uuid4().hex[:12]),
        "text": text,
        "due": _due(item.get("due"), strict=strict),
        "priority": _priority(item.get("priority"), strict=strict),
        "done": bool(item.get("done", False)),
        "tag": _clean(item.get("tag"), MAX_TAG, "tag", strict=strict),
    }
    out.update({k: v for k, v in item.items() if k not in KNOWN})
    return out


def _load(path: Path) -> tuple[list[Any], bool]:
    """Raw entries, plus whether the file used the {"todos": [...]} wrapper."""
    path = Path(path)
    if not path.exists():
        return [], False
    try:
        raw = json.loads(path.read_text() or "[]")
    except json.JSONDecodeError as exc:
        raise TodoError(f"{path.name} is not valid JSON: {exc}") from exc
    wrapped = isinstance(raw, dict)
    if wrapped:
        raw = raw.get("todos", [])
    if not isinstance(raw, list):
        raise TodoError(f"{path.name} should hold a list of reminders")
    return raw, wrapped


def write(path: Path, items: list[dict[str, Any]], *, wrapped: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Any = {"todos": items} if wrapped else items
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(path)        # atomic, so a reader never sees a half-written list


def listing(path: Path) -> list[dict[str, Any]]:
    """Every reminder in the file, done ones included.

    An entry with no `id` gets one, and the file is rewritten once so the id
    sticks. Without that, ids would be reinvented on every read and an edit
    would address whichever row happened to be there last time.
    """
    raw, wrapped = _load(path)
    items = [normalise(entry) for entry in raw]
    items = [item for item in items if item["text"]]
    if any(not isinstance(e, dict) or not e.get("id") for e in raw):
        try:
            write(path, items, wrapped=wrapped)
        except OSError:
            pass                 # a read-only data dir is not worth a 500
    return items


def add(path: Path, fields: dict[str, Any]) -> dict[str, Any]:
    raw, wrapped = _load(path)
    items = [i for i in (normalise(e) for e in raw) if i["text"]]
    if len(items) >= MAX_ITEMS:
        raise TodoError(f"that is already {MAX_ITEMS} reminders; delete some first")
    item = normalise({k: v for k, v in fields.items() if k != "id"}, strict=True)
    items.append(item)
    write(path, items, wrapped=wrapped)
    return item


def update(path: Path, ident: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Merge `fields` onto the stored reminder, so a PUT may be partial."""
    raw, wrapped = _load(path)
    items = [i for i in (normalise(e) for e in raw) if i["text"]]
    for index, current in enumerate(items):
        if current["id"] != ident:
            continue
        merged = dict(current)
        merged.update({k: v for k, v in fields.items() if k != "id"})
        merged["id"] = ident
        items[index] = normalise(merged, strict=True)
        write(path, items, wrapped=wrapped)
        return items[index]
    raise KeyError(ident)


def remove(path: Path, ident: str) -> bool:
    raw, wrapped = _load(path)
    items = [i for i in (normalise(e) for e in raw) if i["text"]]
    kept = [i for i in items if i["id"] != ident]
    if len(kept) == len(items):
        return False
    write(path, kept, wrapped=wrapped)
    return True
