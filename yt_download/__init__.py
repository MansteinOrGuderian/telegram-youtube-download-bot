"""
yt_download — YouTube / YouTube Music download module.

Public API:
    search(query)        -> list[TrackResult]
    resolve_url(url)     -> TrackResult | None
    download(track)      -> Path   (raw .mp3, before tagging)
    apply_metadata(...)  -> Path   (final renamed .mp3)
"""
from yt_download.search import TrackResult, search, resolve_url
from yt_download.downloader import download, DownloadError
from yt_download.metadata import apply_metadata, build_filename

__all__ = [
    "TrackResult",
    "search",
    "resolve_url",
    "download",
    "DownloadError",
    "apply_metadata",
    "build_filename",
]
