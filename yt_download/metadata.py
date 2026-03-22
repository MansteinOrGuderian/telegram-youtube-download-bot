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
from rapidfuzz import fuzz
from mutagen.id3 import (
    ID3,
    APIC,
    TIT2,
    TPE1,
    TPE2,
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

# Matches feat. suffix in titles:
#   "(feat. Bruno Mars)"  - bracketed, may be followed by more content
#   "feat. Artist A, B"   - unbracketed, at end of string
_FEAT_IN_TITLE = re.compile(
    r"\s*(?:"
    r"[\(\[]\s*(?:feat(?:uring)?\.?|ft\.?)\s+([^\)\]]+)[\)\]]"   # (feat. X) or [feat. X]
    r"|(?:feat(?:uring)?\.?|ft\.?)\s+([^\(\[\)\]]+?)\s*$"         # feat. X at end
    r")",
    re.IGNORECASE,
)


def _feat_group(m: re.Match) -> str:
    """Return the captured feat. artist string from either group."""
    return (m.group(1) or m.group(2) or "").strip()


# Patterns to strip from titles for filenames and tags
_TITLE_SUFFIXES = re.compile(
    r"\s*[\(\[]\s*(?:radio\s+(?:edit|version)|single\s+version|album\s+version"
    r"|official\s+audio|official\s+audio\s+version)\s*[\)\]]\s*$",
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
    feat_raw = _feat_group(m)
    # Normalise & to comma for consistent splitting
    feat_raw = feat_raw.replace(" & ", ", ")
    feats = [a.strip() for a in feat_raw.split(",") if a.strip()]
    return main, feats


def build_filename(track: TrackResult) -> str:
    """
    Build the final filename (without directory), e.g.:
        ZAYN feat. Sia - Dusk till Dawn.mp3

    feat. may come from the artist field OR be embedded in the title
    """
    main_artist, feats = _parse_featured(track.artist)

    # If no feat. in artist field, check the title
    clean_title = _FEAT_IN_TITLE.sub("", track.title).strip()
    clean_title = _TITLE_SUFFIXES.sub("", clean_title).strip()
    if not feats:
        m = _FEAT_IN_TITLE.search(track.title)
        if m:
            feat_raw = _feat_group(m)
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
        log.warning("Could not fetch cover from %s: %s", url, exc)
        return None


def _itunes_lookup(artist: str, title: str) -> Optional[dict]:
    """
    Search iTunes API for the track.
    Returns the best-matching result dict, or None if no confident match.
    Result fields of interest: artistName, trackName, collectionName,
    releaseDate, artworkUrl100.
    """
    clean_artist = re.sub(r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+.+$", "", artist, flags=re.IGNORECASE).strip()
    clean_title = _FEAT_IN_TITLE.sub("", title).strip()
    clean_title = _TITLE_SUFFIXES.sub("", clean_title).strip()

    query = f"{clean_artist} {clean_title}"
    try:
        resp = httpx.get(
            "https://itunes.apple.com/search",
            params={"term": query, "entity": "song", "limit": 10},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
    except Exception as exc:
        log.warning("iTunes search failed for %r: %s", query, exc)
        return None

    if not results:
        log.debug("iTunes: no results for %r", query)
        return None

    best_result: Optional[dict] = None
    best_score = 0.0
    for r in results:
        r_artist = r.get("artistName", "")
        r_title_raw = r.get("trackName", "")
        r_title_clean = re.sub(
            r"\s*[\(\[]\s*(?:radio\s+(?:edit|version)|single\s+version)\s*[\)\]]\s*$",
            "", r_title_raw, flags=re.IGNORECASE
        ).strip()

        # Artist and title must BOTH match - check separately
        artist_score = fuzz.token_set_ratio(clean_artist.lower(), r_artist.lower())
        title_score = fuzz.token_set_ratio(clean_title.lower(), r_title_clean.lower())

        # Skip if artist is clearly wrong (prevents cover artists from winning)
        if artist_score < 50:
            continue
        # Skip altered versions - these should never be the preferred result
        if bool(re.search(r"slowed|sped\s*up|nightcore|reverb|lofi|lo-fi|\bremix\b", r_title_raw, re.IGNORECASE)):
            continue

        score = artist_score * 0.5 + title_score * 0.5

        # Prefer proper album tracks
        collection = r.get("collectionName", "") or ""
        is_single_release = bool(re.search(r"\bsingle\b|\bep\b", collection, re.IGNORECASE))
        has_radio_edit = bool(re.search(r"radio\s+edit|radio\s+version", r_title_raw, re.IGNORECASE))
        if not is_single_release and not has_radio_edit:
            score += 15
        elif is_single_release or has_radio_edit:
            score -= 10

        if score > best_score:
            best_score = score
            best_result = r

    if best_score < 60 or best_result is None:
        log.debug("iTunes: no confident match for %r (best score %.0f)", query, best_score)
        return None

    # If best result is a single/radio edit, try a second search explicitly for album version
    best_collection = best_result.get("collectionName", "") or ""
    best_title_raw = best_result.get("trackName", "") or ""
    is_best_single = bool(re.search(r"\bsingle\b|\bep\b", best_collection, re.IGNORECASE))
    has_best_radio = bool(re.search(r"radio\s+edit|radio\s+version", best_title_raw, re.IGNORECASE))

    if is_best_single or has_best_radio:
        log.debug("iTunes: best result is single/radio edit, trying fallback album search (limit=25)")
        try:
            resp2 = httpx.get(
                "https://itunes.apple.com/search",
                params={"term": query, "entity": "song", "limit": 25},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            resp2.raise_for_status()
            all_results = resp2.json().get("results", [])
            log.debug("iTunes fallback: got %d results", len(all_results))
            for r in all_results:
                r_artist = r.get("artistName", "")
                r_title_raw2 = r.get("trackName", "")
                r_collection = r.get("collectionName", "") or ""
                a_score = fuzz.token_set_ratio(clean_artist.lower(), r_artist.lower())
                log.debug("  fallback candidate: %r – %r | collection=%r a_score=%d",
                          r_artist, r_title_raw2, r_collection, a_score)
                if a_score < 50:
                    continue
                is_single_col = bool(re.search(r"\bsingle\b|\bep\b", r_collection, re.IGNORECASE))
                if is_single_col:
                    continue
                if bool(re.search(r"slowed|sped\s*up|nightcore|reverb|lofi|lo-fi", r_title_raw2, re.IGNORECASE)):
                    continue
                # Allow radio edit only if it's on a proper album (not a single release)
                r_title_clean2 = _FEAT_IN_TITLE.sub("", r_title_raw2).strip()
                r_title_clean2 = re.sub(
                    r"\s*[\(\[]\s*(?:radio\s+(?:edit|version))\s*[\)\]]\s*$",
                    "", r_title_clean2, flags=re.IGNORECASE
                ).strip()
                t_score = fuzz.token_set_ratio(clean_title.lower(), r_title_clean2.lower())
                log.debug("    title_score=%d for %r", t_score, r_title_clean2)
                if t_score >= 70:
                    log.debug("iTunes fallback found album version: %r from %r", r_title_raw2, r_collection)
                    best_result = r
                    break
        except Exception as exc:
            log.debug("iTunes fallback failed: %s", exc)

    log.debug("iTunes match: score=%.0f artist=%r title=%r collection=%r type=%s",
              best_score, best_result.get("artistName"), best_result.get("trackName"),
              best_result.get("collectionName"), best_result.get("collectionType"))
    return best_result


def _cover_from_itunes_result(result: dict) -> Optional[bytes]:
    """Download 3000x3000 cover art from an iTunes result dict."""
    url = result.get("artworkUrl100")
    if not url:
        return None
    url = re.sub(r"\d+x\d+bb", "3000x3000bb", url)
    return _fetch_cover(url)


def _get_cover(track: TrackResult, itunes_result: Optional[dict]) -> Optional[bytes]:
    """Fetch cover art: iTunes result first, then YouTube thumbnail as fallback."""
    if itunes_result:
        cover = _cover_from_itunes_result(itunes_result)
        if cover:
            log.debug("Cover art: iTunes ✓")
            return cover

    log.debug("Cover art: iTunes miss — falling back to YouTube thumbnail")
    return _fetch_cover(track.thumbnail_url)


# ID3 tagging

def apply_metadata(mp3_path: Path, track: TrackResult) -> tuple[Path, Optional[bytes], str, str]:
    """
    1. Looks up track on iTunes for authoritative artist/album/title/cover.
    2. Writes ID3 tags (iTunes data preferred, YouTube data as fallback).
    3. Renames file and returns (new_path, cover_bytes, clean_artist, clean_title).
    """
    # Load or create ID3 tag
    try:
        tags = ID3(str(mp3_path))
    except ID3NoHeaderError:
        tags = ID3()

    # iTunes lookup - strip feat. and version markers for cleaner search
    main_artist = re.sub(r"\s+(?:feat(?:uring)?\.?|ft\.?)\s+.+$", "", track.artist, flags=re.IGNORECASE).strip()
    base_title = _FEAT_IN_TITLE.sub("", track.title).strip()
    base_title = _TITLE_SUFFIXES.sub("", base_title).strip()

    itunes = _itunes_lookup(main_artist, base_title)

    # Title
    # iTunes trackName is clean (no feat., no "Radio Edit")
    if itunes:
        clean_title = itunes["trackName"]
        # Strip any feat. or version suffix iTunes might include
        clean_title = _FEAT_IN_TITLE.sub("", clean_title).strip()
        clean_title = _TITLE_SUFFIXES.sub("", clean_title).strip()
    else:
        clean_title = base_title
    tags["TIT2"] = TIT2(encoding=3, text=clean_title)

    # Artist
    # For feat. artists we trust YouTube (correct stage names),
    # for main artist we prefer iTunes (authoritative spelling).
    _, feats = _parse_featured(track.artist)
    if not feats:
        m = _FEAT_IN_TITLE.search(track.title)
        if m:
            feats = [a.strip() for a in _feat_group(m).split(",") if a.strip()]

    if itunes:
        itunes_artist = itunes.get("artistName", main_artist)
        itunes_parts = [p.strip() for p in re.split(r"\s*[&,]\s*", itunes_artist) if p.strip()]
        itunes_parts = list(dict.fromkeys(itunes_parts))
        # Also check iTunes title for feat. artists
        itunes_title_raw = itunes.get("trackName", "")
        m_feat = _FEAT_IN_TITLE.search(itunes_title_raw)
        if m_feat:
            extra = [a.strip() for a in _feat_group(m_feat).split(",") if a.strip()]
            itunes_parts = list(dict.fromkeys(itunes_parts + extra))
        all_artists = itunes_parts
        if len(itunes_parts) > 1:
            filename_artist = f"{itunes_parts[0]} feat. {', '.join(itunes_parts[1:])}"
        else:
            filename_artist = itunes_parts[0]
    else:
        all_artists = list(dict.fromkeys([main_artist] + feats))
        if len(all_artists) > 1:
            filename_artist = f"{all_artists[0]} feat. {', '.join(all_artists[1:])}"
        else:
            filename_artist = all_artists[0]

    artist_for_tag = "; ".join(all_artists)
    tags["TPE1"] = TPE1(encoding=3, text=artist_for_tag)

    # Album artist (TPE2) - main artist only, no feat.
    tags["TPE2"] = TPE2(encoding=3, text=all_artists[0])

    # Album
    # iTunes collectionName is the authoritative album name
    if itunes:
        album_raw: Optional[str] = itunes.get("collectionName") or None
        if album_raw:
            # Strip " - Single", " - EP", " [feat. X]" from iTunes collection names
            album_raw = re.sub(r"\s*-\s*(Single|EP)\s*$", "", album_raw, flags=re.IGNORECASE).strip()
            album_raw = re.sub(r"\s*\[feat\.[^\]]*\]\s*$", "", album_raw, flags=re.IGNORECASE).strip()
            album_raw = album_raw or None
        album: Optional[str] = album_raw
    else:
        album = track.album
        if album and album.lower() == clean_title.lower():
            album = None
    if album:
        tags["TALB"] = TALB(encoding=3, text=album)
    elif "TALB" in tags:
        del tags["TALB"]

    # Year
    year = track.year
    if itunes and itunes.get("releaseDate"):
        try:
            year = int(itunes["releaseDate"][:4])
        except (ValueError, TypeError):
            pass
    if year:
        tags["TDRC"] = TDRC(encoding=3, text=str(year))

    # Cover art
    cover_data = _get_cover(track, itunes)
    if cover_data:
        tags.delall("APIC")
        tags["APIC:"] = APIC(
            encoding=3,
            mime="image/jpeg",
            type=3,
            desc="Cover",
            data=cover_data,
        )
    else:
        log.warning("No cover art found for '%s'", clean_title)

    tags.save(str(mp3_path), v2_version=3)
    log.debug("ID3 tags written for '%s' (iTunes: %s)", clean_title, "✓" if itunes else "✗")

    # Rename
    # Build a synthetic TrackResult with cleaned data for filename
    from dataclasses import replace as dc_replace
    clean_track = dc_replace(track, artist=filename_artist, title=clean_title)
    new_name = build_filename(clean_track)
    new_path = mp3_path.parent / new_name

    mp3_path.rename(new_path)
    log.info("Final file: %s", new_path.name)
    return new_path, cover_data, filename_artist, clean_title
