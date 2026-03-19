"""
Entry point.
Run locally:  python -m app
Run in Docker: python -m app  (CMD in Dockerfile)
"""
from logger import get_logger

log = get_logger(__name__)


def main() -> None:
    log.info("Starting telegram-youtube-download-bot…")
    from app.bot import run
    run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bot stopped.")
