from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import config
import db

router = Router()


def _is_admin(message: Message) -> bool:
    return message.from_user.id in config.ADMIN_IDS


@router.message(Command("report"))
async def report(message: Message):
    if not _is_admin(message):
        return
    count, total = db.report_last_24h()
    await message.answer(
        "📋 گزارش تطبیق مالی — 24 ساعت گذشته\n\n"
        f"تعداد سفارش تایید شده: {count}\n"
        f"جمع مبلغ: {total:,} تومان"
    )


@router.message(F.text == "📦 خرید عمده")
async def bulk_buy(message: Message):
    await message.answer(
        "برای خرید عمده (چند اکانت با تخفیف) لطفاً مستقیم با پشتیبانی صحبت کن:\n"
        f"{config.SUPPORT_USERNAME}"
    )
