from __future__ import annotations

import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from janus.settings import settings
from janus.store import repo as store
from janus.store.schema import Approval
from janus.telegram.formats import approval_card, escape

logger = logging.getLogger(__name__)

_app: Application | None = None
_digest: list[str] = []
_digest_lock = asyncio.Lock()
_awaiting_comment: dict[int, int] = {}

DIGEST_FLUSH_SECONDS = 60
DIGEST_FLUSH_LINES = 10


async def start() -> None:
    global _app
    if not settings.telegram_bot_token:
        logger.warning("no telegram token; approvals will pile up unanswered")
        return
    _app = (
        ApplicationBuilder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(True)
        .build()
    )
    _app.add_handler(CallbackQueryHandler(_on_callback, pattern=r"^apr:"))
    _app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, _on_reply))
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling()
    asyncio.get_running_loop().create_task(_digest_flusher())


async def stop() -> None:
    if _app is not None:
        await _app.updater.stop()
        await _app.stop()
        await _app.shutdown()


async def send_approval(approval: Approval, summary: str, reasons: list[str]) -> None:
    if _app is None:
        logger.info("approval #%s pending (telegram disabled): %s", approval.id, summary)
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"apr:{approval.id}:approve"),
                InlineKeyboardButton("❌ Reject", callback_data=f"apr:{approval.id}:reject"),
            ],
            [
                InlineKeyboardButton(
                    "📝 Reject + comment", callback_data=f"apr:{approval.id}:comment"
                )
            ],
        ]
    )
    message = await _app.bot.send_message(
        chat_id=settings.telegram_chat_id,
        text=approval_card(
            approval.id, approval.repo_full_name, approval.capability, summary, reasons
        ),
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )
    await store.set_approval_message(approval.id, str(message.message_id))


async def notify(text: str) -> None:
    async with _digest_lock:
        _digest.append(text)
        if len(_digest) >= DIGEST_FLUSH_LINES:
            await _flush()


async def _flush() -> None:
    if not _digest or _app is None:
        _digest.clear()
        return
    body = "*Janus digest*\n" + "\n".join(f"• {escape(line)}" for line in _digest)
    _digest.clear()
    try:
        await _app.bot.send_message(
            chat_id=settings.telegram_chat_id, text=body, parse_mode="MarkdownV2"
        )
    except Exception:
        logger.exception("digest send failed")


async def _digest_flusher() -> None:
    while True:
        await asyncio.sleep(DIGEST_FLUSH_SECONDS)
        async with _digest_lock:
            await _flush()


async def _on_callback(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, approval_id_s, action = query.data.split(":")
    approval_id = int(approval_id_s)

    if action == "approve":
        await store.resolve_approval(approval_id, "approved")
        await query.edit_message_text(f"✅ #{approval_id} approved")
    elif action == "reject":
        await store.resolve_approval(approval_id, "rejected")
        await query.edit_message_text(f"❌ #{approval_id} rejected")
    elif action == "comment":
        prompt = await query.message.reply_text(
            f"Reply to this message with the rejection comment for #{approval_id}."
        )
        _awaiting_comment[prompt.message_id] = approval_id
        await query.edit_message_reply_markup(None)


async def _on_reply(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    replied = update.message.reply_to_message
    if replied is None or replied.message_id not in _awaiting_comment:
        return
    approval_id = _awaiting_comment.pop(replied.message_id)
    await store.resolve_approval(approval_id, "rejected", comment=update.message.text)
    await update.message.reply_text(f"❌ #{approval_id} rejected with comment")
