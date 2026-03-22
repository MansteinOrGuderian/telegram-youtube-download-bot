"""
Manual search test — run from project root:
    python test_search.py "Mark Ronson feat. Bruno Mars - Uptown Funk"
    python test_search.py "https://youtu.be/7Ya2U8XN_Zw"
"""
import sys
import re
import os

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "mock")

from yt_download.search import search, resolve_url

_YT_URL = re.compile(r"https?://(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)\S+")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python test_search.py <query or URL>")
        sys.exit(1)

    arg = " ".join(sys.argv[1:])

    if _YT_URL.match(arg):
        print(f"Resolving URL: {arg}\n")
        result = resolve_url(arg)
        if result is None:
            print("❌ Filtered out — not a studio version.")
            return
        results = [result]
    else:
        print(f"Searching: {arg!r}\n")
        results = search(arg)
        if not results:
            print("❌ No studio candidates found.")
            return

    for i, r in enumerate(results, 1):
        print(f"{i:2}. [{r.score:5.1f}] {r.display}")
        print(f"      url={r.url}")
        print(f"      ch={r.channel!r}  dur={r.duration_sec}s  album={r.album!r}  year={r.year}  ytm={r.from_ytmusic}")
        print()


if __name__ == "__main__":
    main()
