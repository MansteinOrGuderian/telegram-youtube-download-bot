"""
Telegram bot application setup and startup.
"""
from telegram.error import NetworkError, TimedOut
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.request import HTTPXRequest

import config
from logger import get_logger
from app.handlers import cmd_start, cmd_history, handle_message, handle_callback

log = get_logger(__name__)


async def _error_handler(update: object, context: object) -> None:
    from telegram.ext import ContextTypes
    ctx = context  # type: ignore[assignment]
    err = getattr(ctx, "error", None)
    if isinstance(err, (NetworkError, TimedOut)):
        log.warning("Network error (auto-retry): %s", err)
    else:
        log.exception("Unhandled error: %s", err)


def run() -> None:
    log.info("Building application…")

    # Increase timeouts for large file uploads (default read_timeout=5s was too low)
    request = HTTPXRequest(
        connect_timeout=10,
        read_timeout=60,
        write_timeout=60,
        media_write_timeout=120,
    )

    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .request(request)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("history", cmd_history))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(_error_handler)

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)
