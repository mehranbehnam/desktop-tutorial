import logging

from aiogram import Bot, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from keyboards import MAIN_MENU

router = Router()
log = logging.getLogger(__name__)

# tg_id -> True while we're waiting for their support message text. Only
# ever set by the support button below, so a stray text message from
# someone who never clicked it is never mistaken for a support request.
_awaiting_support: dict[int, bool] = {}


@router.message(CommandStart())
async def cmd_start(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"👋 به {config.BOT_NAME} خوش اومدی!\n\n"
        "از منوی پایین یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=MAIN_MENU,
    )


@router.message(Command("stop"))
async def stop(message: Message):
    _awaiting_support.pop(message.from_user.id, None)
    await message.answer("باشه، لغو شد.", reply_markup=MAIN_MENU)


@router.message(lambda m: m.text == "🆘 پشتیبانی")
async def support(message: Message):
    _awaiting_support[message.from_user.id] = True
    await message.answer(
        "پیامت رو همینجا بنویس تا مستقیم برای پشتیبانی ارسال بشه.\n"
        f"(یا می‌تونی مستقیم پیام بدی: {config.SUPPORT_USERNAME})"
    )


def _is_awaiting_support(message: Message) -> bool:
    return bool(message.text) and message.from_user.id in _awaiting_support


@router.message(_is_awaiting_support)
async def forward_support_message(message: Message):
    _awaiting_support.pop(message.from_user.id, None)
    if not config.ADMIN_IDS:
        await message.answer("پشتیبانی در حال حاضر در دسترس نیست.")
        return

    who = f"@{message.from_user.username}" if message.from_user.username else str(message.from_user.id)
    text = (
        f"📩 پیام پشتیبانی جدید از {who} (id: {message.from_user.id}):\n\n"
        f"{message.text}"
    )
    reply_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ پاسخ", callback_data=f"supportreply:{message.from_user.id}")
    ]])

    # The admin watches the developer bot, not this one, so the request has
    # to be relayed there — a throwaway Bot instance is enough to send one
    # message; it doesn't need to be polling.
    target_token = config.DEV_BOT_TOKEN or config.BOT_TOKEN
    relay = Bot(token=target_token)
    sent_any = False
    try:
        for admin_id in config.ADMIN_IDS:
            try:
                await relay.send_message(admin_id, text, reply_markup=reply_kb)
                sent_any = True
            except Exception:
                log.exception("failed to relay support message to admin %s", admin_id)
    finally:
        await relay.session.close()

    if sent_any:
        await message.answer("✅ پیام شما برای پشتیبانی ارسال شد. به‌زودی جواب می‌گیری.")
    else:
        await message.answer(f"پیام ارسال نشد؛ مستقیم پیام بده: {config.SUPPORT_USERNAME}")
