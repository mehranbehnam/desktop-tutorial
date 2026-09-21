"""Deliver a service to a user as one package: link, subscription, QR.

Every delivered link ends with one single "📎 اتصال به نرم‌افزار" link —
hermesvpn://import?url=... — that opens the client app with this exact
config already imported (tap Connect and done) if it's installed, or does
nothing if it isn't. The raw links stay visible too (as tap-to-copy code
blocks) for anyone who wants to paste them elsewhere, into a different
client, or to grab the APK separately.
"""
import io
from urllib.parse import quote

import qrcode
from aiogram.types import BufferedInputFile, Message

import config


def app_connect_link(link: str) -> str:
    """Deep link into the client app (see android's intent-filter for the
    "hermesvpn" scheme) that auto-imports `link` as the active config."""
    return f"hermesvpn://import?url={quote(link, safe='')}"


def escape_markdown(text: str) -> str:
    """Escape the characters legacy Telegram Markdown treats as markup, so
    an arbitrary email/label (admin-typed, or a customer's own choice)
    can't break — or silently swallow chunks of — a Markdown-parsed
    message just for containing a stray `_`, `*`, `` ` `` or `[`."""
    for ch in ("\\", "`", "_", "*", "["):
        text = text.replace(ch, "\\" + ch)
    return text


def build_caption(email: str, link: str, sub_url: str = "", header: str = "") -> str:
    # Markdown (legacy), not HTML: vless/sub links are full of unescaped
    # "&" from their query strings, which HTML mode would choke on as
    # broken entities. Markdown only needs backtick/`[`/`_`/`*` escaped —
    # link/sub_url never contain those, but email might, so it alone is escaped.
    parts = []
    if header:
        parts.append(header + "\n")
    parts.append(f"📦 اکانت «{escape_markdown(email)}» — بعد از نصب {config.APP_NAME} روی لینک پایین بزن.")
    parts.append("\n🔗 لینک اتصال (بزن تا کپی بشه):\n`" + link + "`")
    if sub_url:
        parts.append(
            "\n📡 لینک اشتراک/ساب (بزن تا کپی بشه):\n`" + sub_url + "`"
            "\n_با این لینک، سرویس در برنامه خودکار به‌روز می‌شود._"
        )
    parts.append(f"\n📎 [اتصال به نرم‌افزار]({app_connect_link(link)})")
    parts.append("\n📱 یا کد QR بالا را در v2rayNG / NekoBox / Streisand اسکن کن.")
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
            chat_id, make_qr(sub_url or link), caption=caption, parse_mode="Markdown",
        )
    except Exception:
        await bot.send_message(chat_id, caption, parse_mode="Markdown")
