import datetime
import logging

from aiogram import F, Router
from aiogram.types import Message

import db
from xui_client import XUIClient

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == "📶 وضعیت سرویس من")
async def status(message: Message):
    clients = db.get_clients_for_user(message.from_user.id)
    if not clients:
        await message.answer("هنوز سرویس فعالی نداری. از منو «🛒 خرید سرویس» رو بزن.")
        return

    xui = XUIClient()
    lines = []
    for c in clients:
        try:
            traffic = xui.get_client_traffic(c["xui_email"])
        except Exception:
            log.exception("traffic lookup failed for %s", c["xui_email"])
            traffic = None

        expiry = "بدون انقضا" if c["expiry_time"] == 0 else datetime.datetime.fromtimestamp(
            c["expiry_time"] / 1000
        ).strftime("%Y-%m-%d %H:%M")

        if traffic:
            used_gb = (traffic.get("up", 0) + traffic.get("down", 0)) / (1024**3)
            total = c["gb"]
            total_str = "نامحدود" if total == 0 else f"{total} گیگ"
            lines.append(f"• {c['xui_email']}: {used_gb:.2f} گیگ مصرف شده از {total_str} — انقضا: {expiry}")
        else:
            lines.append(f"• {c['xui_email']}: اطلاعات مصرف در دسترس نیست — انقضا: {expiry}")

    await message.answer("📶 وضعیت سرویس‌های شما:\n\n" + "\n".join(lines))


@router.message(F.text == "♻️ دریافت دوباره لینک")
async def resend_link(message: Message):
    clients = db.get_clients_for_user(message.from_user.id)
    if not clients:
        await message.answer("سرویس فعالی برای شما پیدا نشد.")
        return

    xui = XUIClient()
    lines = []
    for c in clients:
        try:
            link = xui.build_vless_link(c["uuid"], c["xui_email"])
            lines.append(f"`{link}`")
        except Exception:
            log.exception("failed to rebuild link for %s", c["xui_email"])

    if not lines:
        await message.answer("در حال حاضر امکان ساخت لینک وجود نداره، با پشتیبانی تماس بگیر.")
        return

    await message.answer("\n\n".join(lines), parse_mode="Markdown")
