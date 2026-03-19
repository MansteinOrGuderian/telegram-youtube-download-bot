"""
    Per-user download history.
    Stores the last N tracks per user_id in memory (resets on bot restart).
    Used to show inline suggestions when the user starts a new search.
"""
from __future__ import annotations

from collections import deque
from typing import NamedTuple

import config

class HistoryEntry(NamedTuple):
    artist: str
    title: str

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"


# { user_id: deque[HistoryEntry] }
_store: dict[int, deque[HistoryEntry]] = {}


def add(user_id: int, artist: str, title: str) -> None:
    """Add a track to the user's history, evicting the oldest if full."""
    if user_id not in _store:
        _store[user_id] = deque(maxlen=config.HISTORY_SIZE)
    entry = HistoryEntry(artist=artist, title=title)
    # Avoid consecutive duplicates
    if not _store[user_id] or _store[user_id][-1] != entry:
        _store[user_id].append(entry)


def get(user_id: int) -> list[HistoryEntry]:
    """Return history newest-first."""
    if user_id not in _store:
        return []
    return list(reversed(_store[user_id]))


def clear(user_id: int) -> None:
    _store.pop(user_id, None)
