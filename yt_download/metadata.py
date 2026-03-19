"""
Handles everything after the raw .mp3 is downloaded:
    1. Build the correct filename  (artist - title.mp3)
    2. Fetch cover art (single cover or album cover, whichever is appropriate)
    3. Write ID3 tags via mutagen (title, artist, album, year, cover art)
    4. Rename the file to its final name and return the new path
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Optional

import httpx
from mutagen.id3 import (
    ID3,
    APIC,
    TIT2,
    TPE1,
    TALB,
    TDRC,
    ID3NoHeaderError,
)

from logger import get_logger
from yt_download.search import TrackResult

log = get_logger(__name__)

# Characters not allowed in filenames on Windows / Linux
_UNSAFE_CHARS = re.compile(r'[\\/*?:"<>|]')
_SEPARATOR = " - "

# Matches feat. suffix in titles: "(feat. Bruno Mars)" / "[ft. X]" / "feat. X"
_FEAT_IN_TITLE = re.compile(
    r"\s*[\(\[]?(?:feat(?:uring)?\.?|ft\.?)\s+(.+?)[\)\]]?\s*$",
    re.IGNORECASE,
)


def _feat_to_comma(artist: str) -> str:
    """Convert 'A feat. B, C' to 'A, B, C' for ID3 artist tag."""
    return re.sub(r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+", ", ", artist, flags=re.IGNORECASE)

def _sanitize(text: str) -> str:
    """Remove / replace characters illegal in filenames; preserve original case."""
    text = _UNSAFE_CHARS.sub("_", text)
    # Normalise unicode (NFC) but keep original characters
    text = unicodedata.normalize("NFC", text)
    return text.strip()


def _parse_featured(artist_raw: str) -> tuple[str, list[str]]:
    """
    Split 'Main Artist feat. A, B' into ('Main Artist', ['A', 'B']).
    Handles: feat. / ft. / featuring (case-insensitive, with or without dot).
    """
    pattern = re.compile(
        r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+(.+)$",
        re.IGNORECASE,
    )
    m = pattern.search(artist_raw)
    if not m:
        return artist_raw.strip(), []

    main = artist_raw[: m.start()].strip()
    feat_raw = m.group(1)
    feats = [a.strip() for a in feat_raw.split(",") if a.strip()]
    return main, feats


def build_filename(track: TrackResult) -> str:
    """
    Build the final filename (without directory), e.g.:
        kryzhana - Десять років.mp3
        МУР feat. Олена Кравець - Суспільна Власність.mp3

    feat. may come from the artist field OR be embedded in the title
    (e.g. title='Суспільна Власність (feat. Олена Кравець)').
    """
    main_artist, feats = _parse_featured(track.artist)

    # If no feat. in artist field, check the title
    clean_title = track.title
    if not feats:
        m = _FEAT_IN_TITLE.search(track.title)
        if m:
            feat_raw = m.group(1)
            feats = [a.strip() for a in feat_raw.split(",") if a.strip()]
            # Remove feat. suffix from title
            clean_title = track.title[: m.start()].strip()

    if feats:
        feat_str = ", ".join(feats)
        artist_part = f"{main_artist} feat. {feat_str}"
    else:
        artist_part = main_artist

    name = f"{_sanitize(artist_part)}{_SEPARATOR}{_sanitize(clean_title)}.mp3"
    return name


# Cover art

def _fetch_cover(url: str) -> Optional[bytes]:
    """Download cover image bytes; return None on any failure."""
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        log.warning("Could not fetch cover art from %s: %s", url, exc)
        return None


def _best_thumbnail(track: TrackResult) -> Optional[bytes]:
    """
    Choose the right artwork:
    - If the track belongs to an album -> album thumbnail (already in track.thumbnail_url,
        which yt-dlp resolves to the best available artwork for that video/release).
    - If it's a single -> the same thumbnail (it's the single cover).
    We trust yt-dlp / YouTube Music to give us the correct cover for the context.
    """
    return _fetch_cover(track.thumbnail_url)


# ID3 tagging

def apply_metadata(mp3_path: Path, track: TrackResult) -> Path:
    """
    1. Writes ID3 tags to the .mp3 file.
    2. Renames the file to its proper `artist - title.mp3` name.
    3. Returns the new Path.
    """
    # Load or create ID3 tag
    try:
        tags = ID3(str(mp3_path))
    except ID3NoHeaderError:
        tags = ID3()

    # Title (clean — strip feat. suffix if present in title)
    clean_title = _FEAT_IN_TITLE.sub("", track.title).strip()
    tags["TIT2"] = TIT2(encoding=3, text=clean_title)

    # Artist — comma-separated for multiple artists (feat. is for filename only)
    # "Mark Ronson feat. Bruno Mars" -> "Mark Ronson, Bruno Mars"
    artist_for_tag = _feat_to_comma(track.artist)
    tags["TPE1"] = TPE1(encoding=3, text=artist_for_tag)

    # Album — skip if album name matches track title (yt-dlp sets this for singles)
    album = track.album
    if album and album.lower() == clean_title.lower():
        album = None
    if album:
        tags["TALB"] = TALB(encoding=3, text=album)
    elif "TALB" in tags:
        del tags["TALB"]

    # Year
    if track.year:
        tags["TDRC"] = TDRC(encoding=3, text=str(track.year))

    # Cover art
    cover_data = _best_thumbnail(track)
    if cover_data:
        # Remove any existing covers first
        tags.delall("APIC")
        tags["APIC:"] = APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,   # 3 = Cover (front)
            desc="Cover",
            data=cover_data,
        )
    else:
        log.warning("No cover art found for '%s'", track.title)

    tags.save(str(mp3_path), v2_version=3)
    log.debug("ID3 tags written for '%s'", track.title)

    # Rename
    new_name = build_filename(track)
    new_path = mp3_path.parent / new_name

    mp3_path.rename(new_path)
    log.info("Final file: %s", new_path.name)
    return new_path
