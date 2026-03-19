# 🎵 telegram-youtube-download-bot

A Telegram bot that downloads **studio/album versions** of songs from YouTube and YouTube Music — with proper ID3 metadata, cover art, and fuzzy search.

## Features

- 🔗 **URL input** — paste any YouTube or YouTube Music link
- 🔍 **Smart search** — find songs by name or artist + name (typo-tolerant, caps-lock-insensitive)
- 🎵 **Studio versions only** — automatically filters out lyric videos, official videos, mood videos, clips, etc.
- 🏷️ **Rich metadata** — title, artist, album, year, and cover art embedded in every MP3
- 🖼️ **Correct cover art** — single cover for singles, album cover for album tracks
- 📋 **Download history** — last 10 downloaded tracks per user
- 🐳 **Docker** — runs in a local container, no cloud needed

## Project structure

```
telegram-youtube-download-bot/
├── app/                  # Telegram bot layer
│   ├── bot.py            # Application setup & startup
│   ├── handlers.py       # Message & command handlers
│   └── history.py        # Per-user download history
├── yt_download/          # YouTube download layer
│   ├── downloader.py     # yt-dlp wrapper
│   ├── search.py         # Search + studio-version filtering
│   └── metadata.py       # ID3 tagging & filename formatting
├── logs/                 # Runtime logs (git-ignored)
├── tmp/                  # Temporary download dir (git-ignored)
├── config.py             # Central config (reads .env)
├── logger.py             # Shared logging setup
├── main.py               # Entry point
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env
```
