"""
Search YouTube / YouTube Music for studio/album tracks and filter out
everything that is NOT a studio version (music videos, lyrics videos,
live performances, covers, remixes, etc.).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import yt_dlp
from rapidfuzz import fuzz

from logger import get_logger

log = get_logger(__name__)

# Patterns that disqualify a result
# Any title/description that matches one of these is NOT a studio version.
_EXCLUDE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bofficial\s+(music\s+)?video\b",
        r"\bofficial\s+clip\b",
        r"\bofficial\s+audio\b",   # often a static image video, not the raw track
        r"\blyric[s]?\s*(video)?\b",
        r"\blyrics?\b",
        r"\bmood\s+video\b",
        r"\blive(\s+version|\s+at|\s+from|\s+performance)?\b",
        r"\bacoustic(\s+version)?\b",
        r"\bcover\b",
        r"\bremix\b",
        r"\bkaraoke\b",
        r"\binstrumental\b",
        r"\bslowed(\s*\+\s*reverb)?\b",
        r"\breverb\b",
        r"\bspeedup\b",
        r"\bnightcore\b",
        r"\bextended\s+mix\b",
        r"\bvideo\s+clip\b",
        r"\bclip\s+officiel\b",
        r"\bteaser\b",
        r"\btrailer\b",
        r"\binterview\b",
        r"\bbehind\s+the\s+scenes?\b",
        r"\blyric\s+visualizer\b",
        r"\bvisuali[sz]er\b",
        r"\baudio\s+only\b",
    ]
]

# These patterns in the UPLOADER/CHANNEL name suggest a non-official source
_CHANNEL_EXCLUDE: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"lyrics?\s*(channel|hub|world|nation|kingdom|official)?\s*$",
        r"karaoke",
        r"covers?(\s+nation)?$",
    ]
]

# YouTube Music search prefix - returns studio tracks by default
_YTM_PREFIX = "https://music.youtube.com/search?q="


@dataclass
class TrackResult:
    video_id: str
    title: str
    artist: str
    album: Optional[str]
    year: Optional[int]
    duration_sec: int
    thumbnail_url: str
    url: str
    score: float = 0.0          # relevance score (higher = better match)
    from_ytmusic: bool = False

    @property
    def display(self) -> str:
        parts = [self.artist, "–", self.title]
        if self.album:
            parts += [f"({self.album})"]
        if self.year:
            parts += [f"[{self.year}]"]
        return " ".join(parts)


def _is_studio(info: dict) -> bool:
    """Return True if the yt-dlp info dict looks like a studio recording."""
    title = info.get("title", "")
    description = info.get("description", "") or ""
    channel = info.get("channel", "") or info.get("uploader", "") or ""

    for pat in _EXCLUDE_PATTERNS:
        if pat.search(title) or pat.search(description[:300]):
            log.debug("Excluded by pattern %r: %s", pat.pattern, title)
            return False

    for pat in _CHANNEL_EXCLUDE:
        if pat.search(channel):
            log.debug("Excluded by channel pattern %r: %s", pat.pattern, channel)
            return False

    return True


def _parse_result(info: dict, from_ytmusic: bool = False) -> Optional[TrackResult]:
    """Convert a yt-dlp info dict to a TrackResult, or None if not studio."""
    if not _is_studio(info):
        return None

    video_id = info.get("id", "")
    title = info.get("track") or info.get("title", "")
    artist = info.get("artist") or info.get("creator") or info.get("uploader", "")
    album = info.get("album")
    year = info.get("release_year") or info.get("upload_date", "0000")[:4]
    try:
        year = int(year) if year else None
    except (ValueError, TypeError):
        year = None

    duration = info.get("duration") or 0
    thumbnail = info.get("thumbnail") or ""
    url = f"https://www.youtube.com/watch?v={video_id}"

    return TrackResult(
        video_id=video_id,
        title=title,
        artist=artist,
        album=album if album else None,
        year=year,
        duration_sec=int(duration),
        thumbnail_url=thumbnail,
        url=url,
        from_ytmusic=from_ytmusic,
    )


def _ydl_search_opts(max_results: int = 10) -> dict:
    return {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "noplaylist": True,
        "default_search": "ytsearch",
        "max_downloads": max_results,
    }


def _fetch_info(url: str) -> Optional[dict]:
    """Fetch full metadata for a single YouTube URL."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as exc:
        log.warning("Failed to fetch info for %s: %s", url, exc)
        return None


def _score(result: TrackResult, query: str) -> float:
    """
    Relevance score 0-100.
    YouTube Music results get a bonus; shorter duration gets a small bonus
    (singles/album tracks are typically 2-5 min, not 1 h DJ sets).
    """
    combined = f"{result.artist} {result.title}"
    base = fuzz.token_set_ratio(query.lower(), combined.lower())

    bonus = 0.0
    if result.from_ytmusic:
        bonus += 15
    if result.album:
        bonus += 5
    # Penalise very long tracks (> 10 min) - likely DJ mixes / compilations
    if result.duration_sec > 600:
        bonus -= 20

    return min(base + bonus, 100.0)


# Public API

def search(query: str, max_results: int = 8) -> list[TrackResult]:
    """
    Search YouTube Music first, then regular YouTube.
    Returns up to `max_results` studio-version candidates ranked by relevance.
    """
    log.info("Searching for: %r", query)
    results: list[TrackResult] = []
    seen: set[str] = set()

    # 1. YouTube Music (ytmsearch - gives better studio metadata)
    ytm_query = f"ytmsearch{max_results}:{query}"
    try:
        with yt_dlp.YoutubeDL(_ydl_search_opts(max_results)) as ydl:
            info = ydl.extract_info(ytm_query, download=False)
            entries = info.get("entries", []) if info else []
            for entry in entries:
                if entry and entry.get("id") not in seen:
                    r = _parse_result(entry, from_ytmusic=True)
                    if r:
                        r.score = _score(r, query)
                        results.append(r)
                        seen.add(entry["id"])
    except Exception as exc:
        log.warning("YouTube Music search failed: %s", exc)

    # 2. Regular YouTube (ytsearch - broader coverage)
    yt_query = f"ytsearch{max_results}:{query}"
    try:
        with yt_dlp.YoutubeDL(_ydl_search_opts(max_results)) as ydl:
            info = ydl.extract_info(yt_query, download=False)
            entries = info.get("entries", []) if info else []
            for entry in entries:
                if entry and entry.get("id") not in seen:
                    r = _parse_result(entry, from_ytmusic=False)
                    if r:
                        r.score = _score(r, query)
                        results.append(r)
                        seen.add(entry["id"])
    except Exception as exc:
        log.warning("YouTube search failed: %s", exc)

    results.sort(key=lambda r: r.score, reverse=True)
    top = results[:max_results]
    log.info("Found %d studio candidates (from %d total)", len(top), len(results))
    return top


def resolve_url(url: str) -> Optional[TrackResult]:
    """
    Resolve a direct YouTube / YouTube Music URL to a TrackResult.
    Returns None if the URL does not look like a studio track.
    """
    log.info("Resolving URL: %s", url)
    info = _fetch_info(url)
    if not info:
        return None

    from_ytmusic = "music.youtube.com" in url
    result = _parse_result(info, from_ytmusic=from_ytmusic)
    if result is None:
        log.warning("URL resolved but filtered as non-studio: %s", url)
    return result
