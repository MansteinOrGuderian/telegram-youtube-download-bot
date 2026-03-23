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
            return
        log.debug("yt-dlp warning: %s", msg)

    def error(self, msg: str) -> None:
        log.debug("yt-dlp error: %s", msg)


_EXCLUDE_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        # English
        r"\bofficial\s+(music\s+)?video\b",
        r"\bofficial\s+clip\b",
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
        r"\bsp(?:ed|eed)\s*up\b",
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
        r"\bvertical\s+video\b",
        r"\bdemo\b",
        # Ukrainian / Cyrillic
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])демо(?![а-яіїєґА-ЯІЇЄҐa-zA-Z])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])живий\s+виступ(?![а-яіїєґА-ЯІЇЄҐ])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])живе\s+виконання(?![а-яіїєґА-ЯІЇЄҐ])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])офіційне\s+відео(?![а-яіїєґА-ЯІЇЄҐ])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])офіційний\s+кліп(?![а-яіїєґА-ЯІЇЄҐ])",
        r"прем['\u2019\u02bcʼ]єра",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])слова(?![а-яіїєґА-ЯІЇЄҐ])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])обкладинка(?![а-яіїєґА-ЯІЇЄҐ])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])кавер(?![а-яіїєґА-ЯІЇЄҐ])",
        r"(?<![а-яіїєґА-ЯІЇЄҐa-zA-Z])ремікс(?![а-яіїєґА-ЯІЇЄҐ])",
    ]
]

_CHANNEL_EXCLUDE: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"lyrics?\s*(channel|hub|world|nation|kingdom|official)?\s*$",
        r"karaoke",
        r"covers?(\s+nation)?$",
    ]
]


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
    channel: str = ""          # original YouTube channel name
    score: float = 0.0
    from_ytmusic: bool = False

    @property
    def display(self) -> str:
        """Short label for Telegram inline keyboard button."""
        artist = self.artist
        title = self.title

        # If artist came from channel (no dedicated artist field), and title contains
        # "Real Artist - Real Title", extract the real artist from title instead
        if self.channel and artist == self.channel and " - " in title:
            parts = title.split(" - ", 1)
            # Use title part after " - " as the display title, first part as artist
            extracted_artist = parts[0].strip()
            extracted_title = parts[1].strip()
            # Only use if extracted artist looks more like a real artist (not too long)
            if len(extracted_artist) < 50:
                artist = extracted_artist
                title = extracted_title

        # Trim extra feat. artists — show only main + first feat.
        artist = re.sub(
            r"(feat\.\s+[^,]+),.*$", r"\1", artist, flags=re.IGNORECASE
        ).strip()

        label = f"{artist} - {title}"
        if self.year:
            label += f" [{self.year}]"
        if len(label) > 60:
            label = label[:57] + "…"
        return label


def _is_studio(info: dict) -> bool:
    """Return True if the yt-dlp info dict looks like a studio recording."""
    title = info.get("title", "")
    description = info.get("description", "") or ""
    channel = info.get("channel", "") or info.get("uploader", "") or ""

    for pat in _EXCLUDE_PATTERNS:
        if pat.search(title):
            log.debug("Excluded by pattern %r: %s", pat.pattern, title)
            return False

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
    thumbnails = info.get("thumbnails")
    if thumbnails:
        sized = [t for t in thumbnails if t.get("url") and t.get("width")]
        if sized:
            return max(sized, key=lambda t: t.get("width", 0))["url"]
        last = thumbnails[-1]
        if last.get("url"):
            return last["url"]
    return info.get("thumbnail") or ""


def _parse_result(info: dict, from_ytmusic: bool = False) -> Optional[TrackResult]:
    """Convert a yt-dlp info dict to a TrackResult, or None if not studio."""
    if not _is_studio(info):
        return None

    video_id = info.get("id", "")
    if not video_id or len(video_id) != 11:
        return None

    title = info.get("track") or info.get("title", "")

    # Comma-separated artists — deduplicate, keep all (authoritative list from platform)
    artist_raw = (
        info.get("artist")
        or info.get("creator")
        or info.get("channel")
        or info.get("uploader", "")
    )
    channel = info.get("channel") or info.get("uploader", "")

    if artist_raw and "," in artist_raw:
        # Deduplicate case-insensitively, preserving original capitalisation of first occurrence
        seen_lower: set[str] = set()
        parts = []
        for a in artist_raw.split(","):
            a = a.strip()
            if a and a.lower() not in seen_lower:
                seen_lower.add(a.lower())
                parts.append(a)
        artist = f"{parts[0]} feat. {', '.join(parts[1:])}" if len(parts) > 1 else parts[0]
    else:
        artist = artist_raw.strip() if artist_raw else ""

    album = info.get("album") or None

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

    duration = info.get("duration") or 0
    if duration > 600:
        log.debug("Excluded by duration (%ds): %s", duration, title)
        return None

    thumbnail = _best_thumbnail_url(info)
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
        channel=channel,
        from_ytmusic=from_ytmusic,
    )


def _ydl_search_opts(max_results: int = 10) -> dict:
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
    """
    Relevance score 0-100.

    Formula:
      base = token_sort_ratio(query, artist+title) x 0.4
            + title_word_coverage x 100 x 0.4
            + channel_artist_match x 20

    Bonuses: ytmusic +15, album +5
    Penalties: duration>600 -20, unrelated artist -25,
               title-duplicates-artist (re-upload) -20
    """
    q = query.lower()
    q_words = set(q.split())
    title_lower = result.title.lower()
    artist_lower = result.artist.lower()
    channel_lower = result.channel.lower()

    # 1. Token sort ratio on full "artist title"
    combined = f"{artist_lower} {title_lower}"
    sort_score = fuzz.token_sort_ratio(q, combined)

    # 2. Title word coverage — fraction of query words found in title
    title_words = set(title_lower.split())
    coverage = len(q_words & title_words) / max(len(q_words), 1)
    # Also penalise if title is a strict subset of query (e.g. "Secret Society" ⊂ "Secret Society Neoperreo")
    if title_words and title_words < q_words:
        coverage *= 0.3

    # 3. Channel-artist match bonus (0-20)
    artist_main = re.sub(
        r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+.+$", "", result.artist, flags=re.IGNORECASE
    ).strip().lower()
    channel_match = fuzz.token_set_ratio(artist_main, channel_lower)
    if channel_match >= 80:
        channel_bonus = 20
    elif channel_match >= 50:
        channel_bonus = 10
    else:
        channel_bonus = 0

    base = sort_score * 0.4 + coverage * 100 * 0.4 + channel_bonus

    # Hard penalty: if title shares no words with query, this is almost certainly wrong
    if coverage == 0:
        base -= 30

    bonus = 0.0
    if result.from_ytmusic:
        bonus += 15
    if result.album:
        bonus += 5
    if result.duration_sec > 600:
        bonus -= 20

    # Artist in query check
    artist_main_words = set(artist_main.split())
    if artist_main_words & q_words:
        bonus += 10
    elif fuzz.partial_ratio(artist_main, q) < 50:
        bonus -= 25

    # Penalise if feat. artists contain names not in query and not matching channel
    # e.g. "Zayn feat. Sia Andrew Lambrou" when query is "Zayn Dusk till Dawn"
    feat_match = re.search(
        r"feat(?:uring)?\.?\s+(.+)$", result.artist, flags=re.IGNORECASE
    )
    if feat_match:
        feat_part = feat_match.group(1).lower()
        feat_words = set(re.sub(r"[,;&]", " ", feat_part).split())
        # Words in feat. that are in neither query nor channel are suspicious
        unknown = feat_words - q_words - set(channel_lower.split())
        if len(unknown) > 1:
            bonus -= 15 * (len(unknown) - 1)

    # Re-upload penalty: title starts with "Artist - " pattern
    if " - " in result.title:
        first_seg = result.title.split(" - ")[0].strip().lower()
        first_seg_words = set(first_seg.split())
        if fuzz.ratio(first_seg, artist_lower) > 60 or fuzz.partial_ratio(artist_lower, first_seg) > 80:
            bonus -= 20
        if len(artist_main_words & first_seg_words) >= len(artist_main_words):
            bonus -= 15

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

    # 1. YouTube Music — flat search for IDs, then enrich each with full metadata
    # Use Songs-only filter (sp param) for more precise results
    ytm_url = f"https://music.youtube.com/search?q={query.replace(' ', '+')}&sp=EgWKAQIIAWoKEAMQBBAJEAoQBQ%3D%3D"
    _flat_fetch = max_results * 3  # fetch 3x more to account for non-song entries
    try:
        with yt_dlp.YoutubeDL(_ytm_search_opts(_flat_fetch)) as ydl:
            info = ydl.extract_info(ytm_url, download=False)
            flat_entries = info.get("entries", []) if info else []

        enriched = 0
        for entry in flat_entries:
            if enriched >= max_results + 2:  # fetch a few extra to filter unavailable
                break
            if not entry:
                continue
            video_id = entry.get("id", "")
            if not video_id or len(video_id) != 11 or video_id in seen:
                continue
            full = _fetch_info(f"https://www.youtube.com/watch?v={video_id}")
            if full is None:
                continue
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
                            if ytmusic_count > 0 and r.score < 50:
                                continue
                            results.append(r)
                            seen.add(entry["id"])
        except Exception as exc:
            log.warning("YouTube search failed: %s", exc)

    results.sort(key=lambda r: r.score, reverse=True)
    results = [r for r in results if r.score >= 30]
    top = results[:max_results]
    log.info("Found %d studio candidates (from %d total)", len(top), len(results))
    for i, r in enumerate(top, 1):
        log.debug(
            "  #%d [%.1f] %s - %s | ch=%r dur=%ds album=%r year=%s ytm=%s",
            i, r.score, r.artist, r.title,
            r.channel, r.duration_sec, r.album, r.year, r.from_ytmusic,
        )
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
