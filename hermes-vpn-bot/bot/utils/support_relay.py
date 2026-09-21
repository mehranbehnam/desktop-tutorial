"""Two-way support chat: a live relay between a customer (sales bot) and
the admins (dev bot), not just a single message + single reply.

Once a customer taps "🆘 پشتیبانی", every message they send keeps going
to the admins until they leave support mode. An admin answers by tapping
"↩️ پاسخ به این گفتگو" on a relayed message — that sets this admin's
active chat target, and every message they send afterward (until they
end the chat) goes straight to that customer.

This used to rely on Telegram's native "reply" gesture (long-press a
message → Reply) instead of a button, matching each admin reply to a
customer by which message got replied to. In practice an admin just
typed a fresh message instead of using that gesture, so nothing was
relayed back — a tap-to-activate button is far harder to miss. No
ticket database: the active-target map only needs to survive one
process's lifetime, same as the single-shot relay this replaces.
"""
import logging

from aiogram import Bot
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import config

log = logging.getLogger(__name__)

EXIT_BUTTON = "⬅️ پایان گفتگو با پشتیبانی"
ADMIN_EXIT_BUTTON = "🔚 پایان گفتگو با مشتری"

# tg_id -> True while a customer is in an active support conversation.
_in_support: set[int] = set()

# admin tg_id -> the customer tg_id they're currently chatting with (set
# by tapping "↩️ پاسخ به این گفتگو" on a relayed message). Sticky until
# they end the chat or tap a different customer's thread.
_active_target: dict[int, int] = {}


def support_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=EXIT_BUTTON)]], resize_keyboard=True)


def admin_chat_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=ADMIN_EXIT_BUTTON)]], resize_keyboard=True)


def start_session(tg_id: int) -> None:
    _in_support.add(tg_id)


def end_session(tg_id: int) -> None:
    _in_support.discard(tg_id)


def in_session(tg_id: int) -> bool:
    return tg_id in _in_support


def set_active_target(admin_id: int, customer_tg_id: int) -> None:
    _active_target[admin_id] = customer_tg_id


def end_active_target(admin_id: int) -> None:
    _active_target.pop(admin_id, None)


def get_active_target(admin_id: int) -> int | None:
    return _active_target.get(admin_id)


async def relay_to_admins(message: Message) -> bool:
    """Forward one customer message to every admin via the dev bot, each
    with a button that starts (or continues) that admin's chat with this
    customer. Returns whether at least one admin actually received it."""
    if not config.ADMIN_IDS:
        await message.answer("پشتیبانی در حال حاضر در دسترس نیست.")
        return False

    who = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    header = f"📩 پشتیبانی — {who} (id: {message.from_user.id}):\n\n"
    body = message.text or message.caption or "(پیام غیرمتنی — لطفاً از مشتری بخواه به‌صورت متن بفرسته)"
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ پاسخ به این گفتگو", callback_data=f"supreply:{message.from_user.id}")
    ]])

    target_token = config.DEV_BOT_TOKEN or config.BOT_TOKEN
    relay = Bot(token=target_token)
    sent_any = False
    try:
        for admin_id in config.ADMIN_IDS:
            try:
                await relay.send_message(admin_id, header + body, reply_markup=reply_kb)
                sent_any = True
            except Exception:
                log.exception("failed to relay support message to admin %s", admin_id)
    finally:
        await relay.session.close()
    return sent_any


async def send_admin_reply(admin_id: int, text: str) -> str:
    """Sends `text` to this admin's active chat target, over the sales
    bot. Returns a short status line for the caller to show the admin."""
    target_tg_id = _active_target.get(admin_id)
    if target_tg_id is None:
        return "گفتگوی فعالی نداری — رو دکمه‌ی «↩️ پاسخ به این گفتگو» بزن."

    sales_bot = Bot(token=config.BOT_TOKEN)
    try:
        await sales_bot.send_message(target_tg_id, f"👤 پشتیبانی:\n\n{text}")
        return "✅ ارسال شد."
    except Exception as e:
        return f"❌ ارسال ناموفق: {type(e).__name__}: {e}"
    finally:
        await sales_bot.session.close()
