import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import config
import db
from keyboards import MAIN_MENU
from utils import support_relay

router = Router()
log = logging.getLogger(__name__)

# Tapping a real main-menu button while "in support mode" should behave
# like tapping it normally (leave support mode, run that button's own
# handler) — not get swallowed and relayed to the admins as if it were a
# support message.
_MAIN_MENU_TEXTS = {btn.text for row in MAIN_MENU.keyboard for btn in row}


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
    support_relay.end_session(message.from_user.id)
    await message.answer("باشه، لغو شد.", reply_markup=MAIN_MENU)


@router.message(lambda m: m.text == "🆘 پشتیبانی")
async def support(message: Message):
    support_relay.start_session(message.from_user.id)
    await message.answer(
        "وارد گفتگو با پشتیبانی شدی — هر چی بفرستی مستقیم می‌ره براشون، و جواب‌شون هم همینجا بهت می‌رسه.\n"
        f"برای خروج «{support_relay.EXIT_BUTTON}» رو بزن.\n"
        f"(یا مستقیم پیام بده: {config.SUPPORT_USERNAME})",
        reply_markup=support_relay.support_keyboard(),
    )


@router.message(lambda m: m.text == support_relay.EXIT_BUTTON)
async def exit_support(message: Message):
    support_relay.end_session(message.from_user.id)
    await message.answer("از گفتگو با پشتیبانی خارج شدی.", reply_markup=MAIN_MENU)


def _is_in_support(message: Message) -> bool:
    if not message.text or not support_relay.in_session(message.from_user.id):
        return False
    if message.text in _MAIN_MENU_TEXTS:
        support_relay.end_session(message.from_user.id)
        return False
    return True


@router.message(_is_in_support)
async def relay_support_message(message: Message):
    sent = await support_relay.relay_to_admins(message)
    if not sent:
        await message.answer(f"پیام ارسال نشد؛ مستقیم پیام بده: {config.SUPPORT_USERNAME}")
