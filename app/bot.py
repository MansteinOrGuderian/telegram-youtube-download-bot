"""
Telegram bot application setup and startup.
"""
from telegram import constants
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
from app.handlers import cmd_start, handle_message, handle_callback

log = get_logger(__name__)


def run() -> None:
    log.info("Building application…")

    # Increase timeouts for large file uploads (default read_timeout=5s is too short)
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
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)
