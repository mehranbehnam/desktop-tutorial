import datetime
import logging

from aiogram import F, Router
from aiogram.types import Message

import db
from utils.delivery import send_service_pack
from xui_client import XUIClient

router = Router()
log = logging.getLogger(__name__)


def _size(num_bytes: int) -> str:
    """Quotas range from a 200 MB trial to 100 GB plans, so pick the unit."""
    gb = num_bytes / (1024**3)
    if gb >= 1:
        return f"{gb:.2f} گیگ"
    return f"{num_bytes / (1024**2):.0f} مگ"


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
            used = traffic.get("up", 0) + traffic.get("down", 0)
            total = traffic.get("total", 0)
            total_str = "نامحدود" if not total else _size(total)
            lines.append(f"• {c['xui_email']}: {_size(used)} مصرف شده از {total_str} — انقضا: {expiry}")
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
    sent = 0
    for c in clients:
        try:
            link = xui.build_vless_link(c["uuid"], c["xui_email"])
            sub_url = xui.get_sub_url(c["xui_email"])
        except Exception:
            log.exception("failed to rebuild link for %s", c["xui_email"])
            continue
        await send_service_pack(message, c["xui_email"], link, sub_url,
                                header=f"♻️ سرویس شما ({c['xui_email']})")
        sent += 1

    if not sent:
        await message.answer("در حال حاضر امکان ساخت لینک وجود نداره، با پشتیبانی تماس بگیر.")
