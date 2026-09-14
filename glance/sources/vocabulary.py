"""Vocabulary decks, and which entry is up right now.

Picked from the clock rather than from stored state: the entry is a pure
function of the time, so it survives a restart, never double-advances on a
device retry, and shows the same word on two panels at once if you point two
at it. That is the same reasoning as the carousel's `clock` mode.

A word of honesty about what this is. Real spaced repetition needs to know
what you got wrong, and a panel on a wall has no way to ask. This is
*scheduled exposure*: each entry gets a slot, the deck cycles, and seeing a
word ten times over a week is what does the work. Calling it an SRS would be
a lie with a nice-sounding name on it.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# Words that begin a noun and carry its gender. Colouring them separately is
# most of what a beginner needs to notice, and costs nothing to draw.
ARTICLES = {
    "es": {"el", "la", "los", "las", "un", "una", "unos", "unas"},
    "fr": {"le", "la", "les", "l'", "un", "une", "des", "du", "de"},
}


@dataclass
class Entry:
    term: str                     # the foreign word or phrase, as written
    gloss: str                    # what it means
    note: str = ""                # a pronunciation hint, or a usage note
    tags: list[str] = field(default_factory=list)

    @property
    def article(self) -> str:
        """The leading article, if the term has one."""
        head = self.term.split(" ", 1)[0].lower()
        return head if any(head in words for words in ARTICLES.values()) else ""

    @property
    def rest(self) -> str:
        return self.term[len(self.article):].lstrip() if self.article else self.term


@dataclass
class Deck:
    language: str
    label: str
    entries: list[Entry]

    def __len__(self) -> int:
        return len(self.entries)

    def order(self, when: datetime, shuffled: bool) -> list[Entry]:
        """The deck, optionally shuffled -- but stably within a day.

        A new order every render would show three words a minute and teach
        none of them; a fixed order means the same word at the same time every
        day. Reshuffling once a day is the compromise.
        """
        if not shuffled:
            return self.entries
        seed = int(hashlib.sha256(
            f"{self.language}:{when:%Y-%m-%d}".encode()).hexdigest()[:8], 16)
        out = list(self.entries)
        random.Random(seed).shuffle(out)
        return out

    def slot(self, when: datetime, rotate: int) -> int:
        return int(when.timestamp()) // max(1, int(rotate))

    def at(self, when: datetime, rotate: int, shuffled: bool = True) -> Entry | None:
        if not self.entries:
            return None
        return self.order(when, shuffled)[self.slot(when, rotate) % len(self.entries)]

    def progress(self, when: datetime, rotate: int) -> float:
        """How far through this entry's slot we are, 0..1."""
        rotate = max(1, int(rotate))
        return (int(when.timestamp()) % rotate) / rotate


def parse_deck(language: str, raw: Any, label: str = "") -> Deck:
    entries: list[Entry] = []
    items = raw.get("words", raw) if isinstance(raw, dict) else raw
    for item in items or []:
        if isinstance(item, str):
            # "el año = the year" is quicker to type than three lines of yaml.
            term, _, gloss = item.partition("=")
            item = {"term": term.strip(), "gloss": gloss.strip()}
        term = str(item.get("term", "") or "").strip()
        gloss = str(item.get("gloss", "") or "").strip()
        if not gloss and "=" in term:
            # `- term: hola = hello` reads as one string to yaml, not as a
            # term and a gloss. Accept it rather than silently dropping the
            # entry, which is what an unglossed word would otherwise get.
            term, _, gloss = (t.strip() for t in term.partition("="))
        if not term or not gloss:
            continue
        tags = item.get("tags") or []
        entries.append(Entry(term=term, gloss=gloss,
                             note=str(item.get("note", "") or "").strip(),
                             tags=[str(t) for t in tags]))
    if isinstance(raw, dict):
        label = str(raw.get("label", label) or label)
    return Deck(language=language, label=label or language.upper(), entries=entries)


class Vocabulary:
    """Every deck found in the vocabulary directory, by language code."""

    def __init__(self, directory: Path) -> None:
        self.dir = Path(directory)
        self.last_error: str | None = None
        self._decks: dict[str, Deck] = {}
        self._mtimes: dict[str, float] = {}

    @property
    def languages(self) -> list[str]:
        self.reload_if_changed()
        return sorted(self._decks)

    def reload_if_changed(self) -> None:
        if not self.dir.exists():
            return
        for path in sorted(self.dir.glob("*.y*ml")):
            code = path.stem.lower()
            try:
                stamp = path.stat().st_mtime
            except OSError:
                continue
            if self._mtimes.get(code) == stamp:
                continue
            try:
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                self._decks[code] = parse_deck(code, raw)
                self._mtimes[code] = stamp
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep the last good deck
                self.last_error = f"{path.name}: {type(exc).__name__}: {exc}"

    def get(self, language: str) -> Deck | None:
        self.reload_if_changed()
        return self._decks.get(str(language or "").lower())

    def status(self) -> dict[str, Any]:
        self.reload_if_changed()
        return {code: {"words": len(deck), "label": deck.label}
                for code, deck in self._decks.items()}
