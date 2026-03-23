"""
Per-user download history.
Persisted to a text file so it survives bot restarts.
Shown as ReplyKeyboard suggestions after each successful download.
"""
from __future__ import annotations

from collections import deque
from typing import NamedTuple

import config

_HISTORY_FILE = config.LOG_DIR / "history.txt"

class HistoryEntry(NamedTuple):
    artist: str
    title: str

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"


# { user_id: deque[HistoryEntry] }
_store: dict[int, deque[HistoryEntry]] = {}


def _load() -> None:
    """Load history from file into memory on startup."""
    if not _HISTORY_FILE.exists():
        return
    try:
        for line in _HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            user_id, artist, title = parts
            uid = int(user_id)
            if uid not in _store:
                _store[uid] = deque(maxlen=config.HISTORY_SIZE)
            _store[uid].append(HistoryEntry(artist=artist, title=title))
    except Exception:
        pass


def _save() -> None:
    """Persist current in-memory history to file."""
    try:
        lines = []
        for user_id, entries in _store.items():
            for e in entries:
                lines.append(f"{user_id}|{e.artist}|{e.title}")
        _HISTORY_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception:
        pass


def add(user_id: int, artist: str, title: str) -> None:
    """Add a track to the user's history, evicting the oldest if full."""
    if user_id not in _store:
        _store[user_id] = deque(maxlen=config.HISTORY_SIZE)
    entry = HistoryEntry(artist=artist, title=title)
    # Avoid consecutive duplicates
    if not _store[user_id] or _store[user_id][-1] != entry:
        _store[user_id].append(entry)
    _save()


def get(user_id: int) -> list[HistoryEntry]:
    """Return history newest-first."""
    if user_id not in _store:
        return []
    return list(reversed(_store[user_id]))


def clear(user_id: int) -> None:
    _store.pop(user_id, None)
    _save()


# Load from disk on import
_load()
