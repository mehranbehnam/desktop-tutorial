"""Deliver a service to a user as one package: link, subscription, QR."""
import io

import qrcode
from aiogram.types import BufferedInputFile, Message

import config


def build_caption(email: str, link: str, sub_url: str = "", header: str = "") -> str:
    parts = []
    if header:
        parts.append(header + "\n")
    parts.append("🔗 *لینک اتصال:*\n`" + link + "`")
    if sub_url:
        parts.append(
            "\n📡 *لینک اشتراک (ساب):*\n`" + sub_url + "`"
            "\n_با این لینک، سرویس در برنامه خودکار به‌روز می‌شود._"
        )
    parts.append("\n📱 کد QR بالا را در v2rayNG / NekoBox / Streisand اسکن کن.")
    return "\n".join(parts)


def make_qr(payload: str) -> BufferedInputFile:
    qr = qrcode.QRCode(box_size=8, border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return BufferedInputFile(buf.getvalue(), filename="config.png")


async def send_service_pack(message: Message, email: str, link: str, sub_url: str = "", header: str = ""):
    """Send the QR image with both links in its caption, as one message.

    The QR encodes the subscription URL when there is one, since that keeps
    working after a renewal; otherwise it encodes the connection link.
    """
    caption = build_caption(email, link, sub_url, header)
    try:
        await message.answer_photo(
            make_qr(sub_url or link), caption=caption, parse_mode="Markdown"
        )
    except Exception:
        # Never lose the config because the image could not be sent.
        await message.answer(caption, parse_mode="Markdown")


async def send_service_pack_to(bot, chat_id: int, email: str, link: str, sub_url: str = "", header: str = ""):
    """Same package, addressed to a chat id (used when an admin approves an order)."""
    caption = build_caption(email, link, sub_url, header)
    try:
        await bot.send_photo(
            chat_id, make_qr(sub_url or link), caption=caption,
            parse_mode="Markdown", reply_markup=_main_menu(),
        )
    except Exception:
        await bot.send_message(chat_id, caption, parse_mode="Markdown", reply_markup=_main_menu())


def _main_menu():
    from keyboards import MAIN_MENU

    return MAIN_MENU
