"""Two-way support chat: a live relay between a customer (sales bot) and
the admins (dev bot), not just a single message + single reply.

Once a customer taps "🆘 پشتیبانی", every message they send keeps going
to the admins until they leave support mode — a real back-and-forth
instead of one relayed message per support request. An admin answers by
using Telegram's own "reply" on the relayed message (long-press → Reply);
that reply goes straight back to that customer. No ticket database: an
in-memory map from (admin chat, relayed message id) to the customer's
tg_id is all that's needed, since it only has to survive one process's
lifetime — a restart just means very old threads can no longer be
replied to, same as the single-shot relay this replaces.
"""
import logging

from aiogram import Bot
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup

import config

log = logging.getLogger(__name__)

EXIT_BUTTON = "⬅️ پایان گفتگو با پشتیبانی"

# tg_id -> True while a customer is in an active support conversation.
_in_support: set[int] = set()

# (admin chat_id, message_id of the relayed copy in that chat) -> the
# customer's tg_id, so an admin's native reply routes back to the right
# person even with several support conversations open at once.
_relay_map: dict[tuple[int, int], int] = {}


def support_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=EXIT_BUTTON)]], resize_keyboard=True)


def start_session(tg_id: int) -> None:
    _in_support.add(tg_id)


def end_session(tg_id: int) -> None:
    _in_support.discard(tg_id)


def in_session(tg_id: int) -> bool:
    return tg_id in _in_support


def is_relayed_message(chat_id: int, message_id: int) -> bool:
    return (chat_id, message_id) in _relay_map


async def relay_to_admins(message: Message) -> bool:
    """Forward one customer message to every admin via the dev bot.
    Returns whether at least one admin actually received it."""
    if not config.ADMIN_IDS:
        await message.answer("پشتیبانی در حال حاضر در دسترس نیست.")
        return False

    who = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    header = f"📩 پشتیبانی — {who} (id: {message.from_user.id}):\n\n"
    body = message.text or message.caption or "(پیام غیرمتنی — لطفاً از مشتری بخواه به‌صورت متن بفرسته)"

    target_token = config.DEV_BOT_TOKEN or config.BOT_TOKEN
    relay = Bot(token=target_token)
    sent_any = False
    try:
        for admin_id in config.ADMIN_IDS:
            try:
                sent = await relay.send_message(admin_id, header + body)
                _relay_map[(sent.chat.id, sent.message_id)] = message.from_user.id
                sent_any = True
            except Exception:
                log.exception("failed to relay support message to admin %s", admin_id)
    finally:
        await relay.session.close()
    return sent_any


async def relay_admin_reply(message: Message) -> None:
    """Send an admin's reply-to-a-relayed-message back to that customer,
    over the sales bot. Caller (devmenu.py) only invokes this once
    is_relayed_message() has already confirmed the reply target."""
    target_tg_id = _relay_map[(message.chat.id, message.reply_to_message.message_id)]

    sales_bot = Bot(token=config.BOT_TOKEN)
    try:
        await sales_bot.send_message(target_tg_id, f"👤 پشتیبانی:\n\n{message.text}")
        await message.answer("✅ ارسال شد.")
    except Exception as e:
        await message.answer(f"❌ ارسال ناموفق: {type(e).__name__}: {e}")
    finally:
        await sales_bot.session.close()
