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


class _YtdlpLogger:
    """Redirects yt-dlp output to our logger instead of stdout/stderr."""
    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            log.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        if "No supported JavaScript runtime" in msg:
            return  # expected on systems without node/deno — not actionable
        log.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        log.debug("yt-dlp error: %s", msg)

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
        if pat.search(title):
            log.debug("Excluded by pattern %r: %s", pat.pattern, title)
            return False

    # Check description only for patterns unlikely to appear in normal descriptions
    _DESC_PATTERNS = {r"\bmood\s+video\b", r"\blyric\s+visualizer\b", r"\bvisuali[sz]er\b"}
    for pat in _EXCLUDE_PATTERNS:
        if pat.pattern in _DESC_PATTERNS and pat.search(description[:300]):
            log.debug("Excluded by desc pattern %r: %s", pat.pattern, title)
            return False

    for pat in _CHANNEL_EXCLUDE:
        if pat.search(channel):
            log.debug("Excluded by channel pattern %r: %s", pat.pattern, channel)
            return False

    return True


def _best_thumbnail_url(info: dict) -> str:
    """
    Return the highest-resolution thumbnail URL from the info dict.
    yt-dlp provides a 'thumbnails' list sorted by quality, and a 'thumbnail'
    shortcut. We prefer the largest by resolution, falling back to 'thumbnail'.
    """
    thumbnails = info.get("thumbnails")
    if thumbnails:
        # Filter entries that have a url and at least width info
        sized = [t for t in thumbnails if t.get("url") and t.get("width")]
        if sized:
            best = max(sized, key=lambda t: t.get("width", 0))
            return best["url"]
        # Fallback: last entry (yt-dlp usually puts best last)
        last = thumbnails[-1]
        if last.get("url"):
            return last["url"]
    return info.get("thumbnail") or ""


def _parse_result(info: dict, from_ytmusic: bool = False) -> Optional[TrackResult]:
    """Convert a yt-dlp info dict to a TrackResult, or None if not studio."""
    if not _is_studio(info):
        return None

    video_id = info.get("id", "")
    # YouTube video IDs are always exactly 11 characters — filter out playlists/channels
    if not video_id or len(video_id) != 11:
        return None

    # extract_flat returns "track" for YTMusic, "title" for regular YouTube
    title = info.get("track") or info.get("title", "")

    # "artist" field can be comma-joined list — first is main, rest are featured
    artist_raw = (
        info.get("artist")
        or info.get("creator")
        or info.get("channel")
        or info.get("uploader", "")
    )
    if artist_raw and "," in artist_raw:
        parts = [a.strip() for a in artist_raw.split(",") if a.strip()]
        artist = f"{parts[0]} feat. {', '.join(parts[1:])}"
    else:
        artist = artist_raw.strip() if artist_raw else ""

    album = info.get("album") or None

    # Validate year — yt-dlp sometimes returns bogus values
    year: Optional[int] = None
    for field in ("release_year", "upload_date"):
        raw = info.get(field)
        if not raw:
            continue
        try:
            y = int(str(raw)[:4])
            if 1900 <= y <= 2100:
                year = y
                break
        except (ValueError, TypeError):
            continue

    # extract_flat returns duration=0; treat it as unknown rather than 0
    duration = info.get("duration") or 0
    if duration > 600:
        log.debug("Excluded by duration (%ds): %s", duration, title)
        return None

    thumbnail = _best_thumbnail_url(info)
    if not thumbnail:
        log.debug("No thumbnail found for video_id=%s title=%r", video_id, title)
    url = f"https://www.youtube.com/watch?v={video_id}"

    return TrackResult(
        video_id=video_id,
        title=title,
        artist=artist,
        album=album,
        year=year,
        duration_sec=int(duration),
        thumbnail_url=thumbnail,
        url=url,
        from_ytmusic=from_ytmusic,
    )


def _ydl_search_opts(max_results: int = 10) -> dict:
    """Regular YouTube search — extract_flat for speed."""
    return {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "noplaylist": True,
        "max_downloads": max_results,
        "logger": _YtdlpLogger(),
    }


def _ytm_search_opts(max_results: int = 10) -> dict:
    """YouTube Music search — extract_flat for speed."""
    return {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
        "noplaylist": True,
        "max_downloads": max_results,
        "logger": _YtdlpLogger(),
    }


def _fetch_info(url: str) -> Optional[dict]:
    """Fetch full metadata for a single YouTube URL."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "logger": _YtdlpLogger(),
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as exc:
        log.warning("Failed to fetch info for %s: %s", url, exc)
        return None


def _score(result: TrackResult, query: str) -> float:
    combined = f"{result.artist} {result.title}"
    base = fuzz.token_set_ratio(query.lower(), combined.lower())

    bonus = 0.0
    if result.from_ytmusic:
        bonus += 15
    if result.album:
        bonus += 5
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

    # 1. YouTube Music — flat search for IDs, enrich top results one by one
    ytm_url = f"https://music.youtube.com/search?q={query.replace(' ', '+')}"
    try:
        with yt_dlp.YoutubeDL(_ytm_search_opts(max_results)) as ydl:
            info = ydl.extract_info(ytm_url, download=False)
            flat_entries = info.get("entries", []) if info else []

        enriched = 0
        for entry in flat_entries:
            if enriched >= max_results:
                break
            if not entry:
                continue
            video_id = entry.get("id", "")
            if not video_id or len(video_id) != 11 or video_id in seen:
                continue
            url = f"https://www.youtube.com/watch?v={video_id}"
            full = _fetch_info(url)
            if full is None:
                continue  # unavailable — skip without counting
            enriched += 1
            r = _parse_result(full, from_ytmusic=True)
            if r:
                r.score = _score(r, query)
                results.append(r)
                seen.add(video_id)
    except Exception as exc:
        log.warning("YouTube Music search failed: %s", exc)

    # 2. Regular YouTube — only if YTMusic didn't fill the list
    ytmusic_count = len(results)
    if ytmusic_count < max_results:
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
                            # Skip low-relevance YT results if we already have YTMusic hits
                            if ytmusic_count > 0 and r.score < 50:
                                continue
                            results.append(r)
                            seen.add(entry["id"])
        except Exception as exc:
            log.warning("YouTube search failed: %s", exc)

    results.sort(key=lambda r: r.score, reverse=True)
    # Drop clearly irrelevant results (score below threshold)
    results = [r for r in results if r.score >= 30]
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
