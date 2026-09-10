import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import Message

import config
import db
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == "🧪 تست")
async def trial(message: Message, bot: Bot):
    tg_id = message.from_user.id
    if db.has_used_trial(tg_id):
        await message.answer("شما قبلاً از سرویس تست استفاده کردی. برای ادامه یکی از پلن‌ها رو بخر.")
        return

    email = f"trial{tg_id}-{int(time.time())}"
    try:
        client = XUIClient().add_client(email=email, gb=config.TRIAL_GB, hours=config.TRIAL_HOURS)
        link = XUIClient().build_vless_link(client["uuid"], email)
    except XUIError:
        log.exception("trial provisioning failed for %s", tg_id)
        await message.answer("خطا در ساخت اکانت تست، لطفاً بعداً دوباره امتحان کن یا با پشتیبانی تماس بگیر.")
        return

    db.save_client(email, tg_id, client["uuid"], config.TRIAL_GB, client["expiry_time"])
    db.mark_trial_used(tg_id)

    await message.answer(
        f"🧪 اکانت تست ساخته شد ({config.TRIAL_GB} گیگ / {config.TRIAL_HOURS} ساعت):\n\n"
        f"`{link}`",
        parse_mode="Markdown",
    )
