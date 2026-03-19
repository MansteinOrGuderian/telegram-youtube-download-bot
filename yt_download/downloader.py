"""
Downloads a track from YouTube as a high-quality MP3 using yt-dlp + ffmpeg.
Returns the path to the finished file inside a temporary directory.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import yt_dlp

import config
from logger import get_logger
from yt_download.search import TrackResult

log = get_logger(__name__)


class DownloadError(Exception):
    """Raised when yt-dlp fails to download or convert a track."""


def _build_opts(out_dir: str, quality: str) -> dict:
    return {
        # Best audio source available
        "format": "bestaudio/best",
        # Convert to MP3 via ffmpeg
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            },
            # Write thumbnail so we can embed it ourselves with mutagen
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "jpg",
            },
            {
                "key": "EmbedThumbnail",
            },
        ],
        # Temporary filename — will be renamed properly in metadata.py
        "outtmpl": f"{out_dir}/%(id)s.%(ext)s",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Write thumbnail file alongside audio (used as fallback for cover art)
        "writethumbnail": True,
        # Ensure ffmpeg is used for merging
        "prefer_ffmpeg": True,
    }


def download(track: TrackResult) -> Path:
    """
    Download track as MP3 into a fresh temp directory.

    Returns:
        Path to the downloaded .mp3 file (before metadata/renaming).

    Raises:
        DownloadError: if yt-dlp fails for any reason.
    """
    tmp_dir = tempfile.mkdtemp(prefix="ytdlbot_")
    log.info("Downloading '%s - %s'  →  %s", track.artist, track.title, tmp_dir)

    ydl_opts = _build_opts(tmp_dir, config.AUDIO_QUALITY)

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([track.url])
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(f"yt-dlp error: {exc}") from exc
    except Exception as exc:
        raise DownloadError(f"Unexpected download error: {exc}") from exc

    # Find the produced .mp3 file
    mp3_files = list(Path(tmp_dir).glob("*.mp3"))
    if not mp3_files:
        raise DownloadError(f"No MP3 produced in {tmp_dir}")

    mp3_path = mp3_files[0]
    log.info("Downloaded: %s  (%.1f MB)", mp3_path.name, mp3_path.stat().st_size / 1_048_576)

    _check_size(mp3_path)
    return mp3_path


def _check_size(path: Path) -> None:
    size_mb = path.stat().st_size / 1_048_576
    limit = config.MAX_FILE_SIZE_MB
    if size_mb > limit:
        raise DownloadError(
            f"File is {size_mb:.1f} MB — exceeds Telegram limit of {limit} MB."
        )
