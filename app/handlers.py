"""
Telegram message and callback handlers.

Flow:
  1. User sends a URL or search query
  2. Bot resolves/searches → shows a list of candidates as inline buttons
  3. User taps a result → bot downloads, tags, and sends the MP3
"""
from __future__ import annotations

import asyncio
import re

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import ContextTypes
from telegram.constants import ChatAction

import config
from logger import get_logger
from app import history as hist
from yt_download.search import search as yt_search_fn, resolve_url as yt_resolve_url, TrackResult
from yt_download import download, apply_metadata, DownloadError

log = get_logger(__name__)

# Matches any YouTube or YouTube Music URL
_YOUTUBE_URL_PATTERN = re.compile(
    r"https?://(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)\S+"
)

# Prefix for inline keyboard callback data — format: "select:<video_id>"
_CALLBACK_SELECT_PREFIX = "select:"
_CALLBACK_CANCEL = "cancel"


def _is_allowed(user_id: int) -> bool:
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


def _history_keyboard(user_id: int) -> ReplyKeyboardMarkup | None:
    """Return a reply keyboard with the user's recent downloads, or None."""
    entries = hist.get(user_id)
    if not entries:
        return None
    buttons = [[KeyboardButton(str(e))] for e in entries]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)


def _results_keyboard(results: list[TrackResult]) -> InlineKeyboardMarkup:
    """Inline keyboard: one button per search result + cancel."""
    buttons = [
        [InlineKeyboardButton(r.display, callback_data=f"{_CALLBACK_SELECT_PREFIX}{r.video_id}")]
        for r in results
    ]
    buttons.append([InlineKeyboardButton("❌ Відміна", callback_data=_CALLBACK_CANCEL)])
    return InlineKeyboardMarkup(buttons)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_user is not None
    assert update.effective_message is not None
    user = update.effective_user
    if not _is_allowed(user.id):
        return

    keyboard = _history_keyboard(user.id)
    text = (
        "👋 Привіт!\n\n"
        "Надішли мені:\n"
        "• посилання на YouTube або YouTube Music\n"
        "• або назву треку / виконавець + назва\n\n"
        "Я знайду студійну версію і скину MP3 з тегами 🎵"
    )
    await update.effective_message.reply_text(text, reply_markup=keyboard)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a URL or a text search query."""
    assert update.effective_user is not None
    assert update.effective_message is not None
    user = update.effective_user
    if not _is_allowed(user.id):
        return

    text = update.effective_message.text
    assert text is not None
    text = text.strip()
    log.info("User %d sent: %r", user.id, text)

    if _YOUTUBE_URL_PATTERN.match(text):
        await _handle_url(update, context, text)
    else:
        await _handle_search(update, context, text)


async def _handle_url(
    update: Update, context: ContextTypes.DEFAULT_TYPE, url: str
) -> None:
    assert update.effective_message is not None
    msg = await update.effective_message.reply_text("🔍 Перевіряю посилання…")
    result = await asyncio.to_thread(yt_resolve_url, url)

    if result is None:
        await msg.edit_text(
            "❌ Не вдалося розпізнати трек.\n"
            "Переконайся що це посилання на студійну версію (не кліп, не live)."
        )
        return

    assert context.user_data is not None
    context.user_data["pending"] = {result.video_id: result}
    await msg.edit_text(f"✅ Знайдено: {result.display}\n\n⬇️ Завантажую…")
    await _download_and_send(update, context, result)


async def _handle_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE, query: str
) -> None:
    assert update.effective_message is not None
    msg = await update.effective_message.reply_text("🔍 Шукаю…")
    results = await asyncio.to_thread(yt_search_fn, query)

    if not results:
        await msg.edit_text("😕 Нічого не знайшов. Спробуй інший запит.")
        return

    assert context.user_data is not None
    context.user_data["pending"] = {r.video_id: r for r in results}
    await msg.edit_text(
        "🎵 Оберіть трек:",
        reply_markup=_results_keyboard(results),
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button tap — user selected a search result."""
    assert update.callback_query is not None
    query = update.callback_query
    await query.answer()

    assert query.data is not None
    if query.data == _CALLBACK_CANCEL:
        await query.edit_message_text("❌ Скасовано.")
        return

    if not query.data.startswith(_CALLBACK_SELECT_PREFIX):
        return

    video_id = query.data[len(_CALLBACK_SELECT_PREFIX):]
    assert context.user_data is not None
    pending: dict[str, TrackResult] = context.user_data.get("pending", {})
    result = pending.get(video_id)

    if result is None:
        await query.edit_message_text("⚠️ Результат більше недоступний. Спробуй ще раз.")
        return

    await query.edit_message_text(f"⬇️ Завантажую: {result.display}…")
    await _download_and_send(update, context, result)


async def _download_and_send(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    track: TrackResult,
) -> None:
    assert update.effective_message is not None
    assert update.effective_user is not None
    effective_message = update.effective_message
    user = update.effective_user

    try:
        await context.bot.send_chat_action(
            chat_id=effective_message.chat_id,
            action=ChatAction.UPLOAD_DOCUMENT,
        )

        mp3_path = await asyncio.to_thread(download, track)
        final_path = await asyncio.to_thread(apply_metadata, mp3_path, track)

        with open(final_path, "rb") as f:
            await context.bot.send_audio(
                chat_id=effective_message.chat_id,
                audio=f,
                title=track.title,
                performer=track.artist,
                filename=final_path.name,
            )

        hist.add(user.id, track.artist, track.title)
        log.info("Sent '%s' to user %d", final_path.name, user.id)

        try:
            final_path.unlink()
            final_path.parent.rmdir()
        except Exception:
            pass

    except DownloadError as exc:
        log.error(
            "DownloadError for user %d | url=%s | track='%s - %s' | error=%s",
            user.id, track.url, track.artist, track.title, exc,
        )
        await effective_message.reply_text(f"❌ Помилка завантаження:\n{exc}")
    except Exception:
        log.exception(
            "Unexpected error for user %d | url=%s | track='%s - %s'",
            user.id, track.url, track.artist, track.title,
        )
        await effective_message.reply_text("❌ Щось пішло не так. Спробуй пізніше.")
