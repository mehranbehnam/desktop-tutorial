from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

import config
import db
from keyboards import MAIN_MENU

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"👋 به {config.BOT_NAME} خوش اومدی!\n\n"
        "از منوی پایین یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=MAIN_MENU,
    )


@router.message(lambda m: m.text == "🆘 پشتیبانی")
async def support(message: Message):
    await message.answer(f"برای پشتیبانی پیام بده: {config.SUPPORT_USERNAME}")
