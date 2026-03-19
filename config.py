"""
Central configuration — reads from environment / .env file.
Import this module everywhere instead of os.getenv() directly.
"""
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _required(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise RuntimeError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, default))


def _list(key: str) -> list[int]:
    raw = os.getenv(key, "").strip()
    if not raw:
        return []
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def _optional_int(key: str) -> int | None:
    raw = os.getenv(key)
    return int(raw) if raw else None


# Telegram
BOT_TOKEN: str = _required("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS: list[int] = _list("ALLOWED_USER_IDS")
ADMIN_USER_ID: int | None = _optional_int("ADMIN_USER_ID")

# Paths
BASE_DIR = Path(__file__).parent
TMP_DIR = Path(tempfile.gettempdir())
LOG_DIR = BASE_DIR / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)

# Download
MAX_FILE_SIZE_MB: int = _int("MAX_FILE_SIZE_MB", 50)
AUDIO_QUALITY: str = os.getenv("AUDIO_QUALITY", "320")

# History
HISTORY_SIZE: int = _int("HISTORY_SIZE", 10)

# Logging
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
