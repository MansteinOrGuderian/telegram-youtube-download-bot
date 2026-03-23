# 🎵 telegram-youtube-download-bot

A Telegram bot that downloads **studio/album versions** of songs from YouTube and YouTube Music — with proper ID3 metadata, cover art, and fuzzy search.

## Features

- 🔗 **URL input** — paste any YouTube or YouTube Music link
- 🔍 **Smart search** — find songs by name or artist + name (typo-tolerant, caps-lock-insensitive)
- 🎵 **Studio versions only** — automatically filters out lyric videos, official videos, live performances, remixes, etc.
- 🖼️ **High-quality cover art** — 3000×3000 from iTunes, YouTube thumbnail as fallback
- 📋 **Download history** — last 10 downloads shown by `/history` command

## Bot usage

| Input                    | Example                                         |
|--------------------------|-------------------------------------------------|
| YouTube URL              | `https://www.youtube.com/watch?v=7Ya2U8XN_Zw`   |
| YouTube Music URL        | `https://music.youtube.com/watch?v=7Ya2U8XN_Zw` |
| Search by title          | `Uptown Funk`                                   |
| Search by artist + title | `Bruno Mars Uptown Funk`                        |

After a text search the bot shows a list of candidates as inline buttons. Tap a track to download it, or press ❌ to cancel. Use `/history` to see your last downloaded tracks.


## File naming & tags

Filename format: `Artist feat. FeatArtist - Title.mp3`

| Tag          | Source                                                    |
|--------------|-----------------------------------------------------------|
| Title        | iTunes → Deezer → YouTube                                 |
| Artist       | iTunes → Deezer (stage names, no real names) → YouTube    |
| Album artist | Main artist only (no feat.)                               |
| Album        | iTunes → Deezer → YouTube; omitted for standalone singles |
| Year         | iTunes → Deezer → YouTube                                 |
| Cover art    | iTunes 3000×3000 → Deezer 1000×1000 → YouTube thumbnail   |

## Project structure

```
telegram-youtube-download-bot/
├── app/                  # Telegram bot layer
│   ├── __init__.py
│   ├── __main__.py       # Entry point — python -m app
│   ├── bot.py            # Application setup & startup
│   ├── handlers.py       # Message & command handlers
│   └── history.py        # User download history (inline suggestions)
├── yt_download/          # YouTube download layer
│   ├── __init__.py
│   ├── downloader.py     # yt-dlp wrapper
│   ├── search.py         # Search + studio-version filtering + scoring
│   └── metadata.py       # iTunes lookup, ID3 tagging, filename formatting
├── logs/                 # Runtime logs (content git-ignored)
├── config.py             # Central config (reads .env)
├── logger.py             # Shared logging setup
├── test_search.py        # Manual search test script
├── mypy.ini
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Quick start

```bash
git clone https://github.com/your-username/telegram-youtube-download-bot.git
cd telegram-youtube-download-bot

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create .env and set at minimum TELEGRAM_BOT_TOKEN
cp .env.example .env

python -m app
```

## Configuration

All settings are read from a `.env` file in the project root.

| Variable             | Default         | Description                                     |
|----------------------|-----------------|-------------------------------------------------|
| `TELEGRAM_BOT_TOKEN` | **required**    | Get from [@BotFather](https://t.me/BotFather)   |
| `ALLOWED_USER_IDS`   | *(empty = all)* | Comma-separated Telegram user IDs to whitelist  |
| `ADMIN_USER_ID`      | *(optional)*    | Your personal Telegram user ID                  |
| `AUDIO_QUALITY`      | `320`           | MP3 bitrate in kbps: 128 / 192 / 256 / 320      |
| `MAX_FILE_SIZE_MB`   | `50`            | Max file size — Telegram bot limit is 50 MB     |
| `HISTORY_SIZE`       | `10`            | Number of recent downloads to remember per user |
| `LOG_LEVEL`          | `INFO`          | `DEBUG` / `INFO` / `WARNING` / `ERROR`          |
