"""
Shared logger. Import `get_logger(__name__)` in every module.
"""
import logging
import sys

try:
    import colorlog
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False

import config

_LOG_FILE = config.LOG_DIR / "bot.log"
_initialized = False


def _setup() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True

    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"

    # Console handler
    if _HAS_COLOR:
        color_fmt = (
            "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s "
            "%(cyan)s%(name)s%(reset)s: %(message)s"
        )
        console_handler = colorlog.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            colorlog.ColoredFormatter(
                color_fmt,
                datefmt=date_fmt,
                log_colors={
                    "DEBUG":    "white",
                    "INFO":     "green",
                    "WARNING":  "yellow",
                    "ERROR":    "red",
                    "CRITICAL": "bold_red",
                },
            )
        )
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))

    root.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "telegram", "yt_dlp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    _setup()
    return logging.getLogger(name)
