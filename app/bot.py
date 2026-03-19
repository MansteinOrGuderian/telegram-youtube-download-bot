"""
Telegram bot application setup and startup.
"""
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import config
from logger import get_logger
from app.handlers import cmd_start, handle_message, handle_callback

log = get_logger(__name__)


def run() -> None:
    log.info("Building application…")

    app = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)
