import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from utils.delivery import app_connect_link, escape_markdown, send_service_pack
from xui_client import XUIClient

router = Router()
log = logging.getLogger(__name__)

ACCOUNTS_PAGE_SIZE = 6
# tg_id -> email currently waiting for a new custom label.
_RENAME_WAIT: dict[int, str] = {}

# Repeatedly mashing "resend link" gains nothing for a legitimate customer
# (the link doesn't change), so more than a few in an hour is almost always
# either a broken client stuck retrying or someone probing/abusing the bot
# — either way it's cheaper to pause the account and have a human look than
# to let it keep going.
RESEND_LIMIT = 5
RESEND_WINDOW_S = 3600
_resend_log: dict[int, list[float]] = {}


def _resend_abuse(tg_id: int) -> bool:
    now = time.time()
    hits = [t for t in _resend_log.get(tg_id, []) if now - t < RESEND_WINDOW_S]
    hits.append(now)
    _resend_log[tg_id] = hits
    return len(hits) > RESEND_LIMIT


def _fmt_size(num_bytes: int) -> str:
    """Megabytes below a gigabyte — the 200MB trial plan rendered as "0GB",
    which looks to the customer like a broken account rather than a small one."""
    n = max(0, num_bytes or 0)
    if n < 1024**3:
        return f"{n / 1024**2:.0f} مگ"
    return f"{n / 1024**3:.2f} گیگ"


def _fmt_size_en(num_bytes: int) -> str:
    """Same idea as _fmt_size but GB/MB instead of گیگ/مگ, and no trailing
    ".00" on a round number — used only on the single-account detail card,
    where "20GB" reads cleaner than "20.00GB"."""
    n = max(0, num_bytes or 0)
    if n < 1024**3:
        return f"{n / 1024**2:.0f}MB"
    gb = n / 1024**3
    return f"{gb:.0f}GB" if gb == int(gb) else f"{gb:.2f}GB"


def _remaining_time(expiry_ms: int) -> str:
    if not expiry_ms:
        return "بدون انقضا"
    remain = expiry_ms - time.time() * 1000
    if remain <= 0:
        return "منقضی"
    days = int(remain / 86400000)
    if days >= 1:
        return f"{days} روز"
    hours = int(remain / 3600000)
    return f"{hours} ساعت" if hours >= 1 else "کمتر از ۱ ساعت"


def _account_line(client: dict, used: int, label: str | None) -> str:
    total_bytes = client["gb"] * 1024**3 if client["gb"] else 0
    vol = "نامحدود" if not total_bytes else _fmt_size(max(0, total_bytes - used))
    return f"{label or client['xui_email']} • {vol} • {_remaining_time(client['expiry_time'])}"


def _accounts_keyboard(xui: XUIClient, clients: list, page: int):
    labels = db.get_labels([c["xui_email"] for c in clients])
    online = xui.get_online_emails()
    start = page * ACCOUNTS_PAGE_SIZE
    chunk = clients[start:start + ACCOUNTS_PAGE_SIZE]
    rows = []
    for c in chunk:
        traffic = xui.get_client_traffic(c["xui_email"]) or {}
        used = traffic.get("up", 0) + traffic.get("down", 0)
        enable = traffic.get("enable", True)
        dot = "🔒 " if not enable else ("🔵 " if c["xui_email"] in online else "🔴 ")
        text = dot + _account_line(c, used, labels.get(c["xui_email"]))
        rows.append([InlineKeyboardButton(text=text, callback_data=f"acc:view:{c['xui_email']}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"acc:page:{page-1}"))
    if start + ACCOUNTS_PAGE_SIZE < len(clients):
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"acc:page:{page+1}"))
    if nav:
        rows.append(nav)
    online_count = sum(1 for c in clients if c["xui_email"] in online)
    return InlineKeyboardMarkup(inline_keyboard=rows), online_count


def _status_header(total: int, page: int, online_count: int) -> str:
    pages = (total + ACCOUNTS_PAGE_SIZE - 1) // ACCOUNTS_PAGE_SIZE
    return (
        f"📶 سرویس‌های تو ({total} اکانت" + (f" — صفحه {page+1} از {pages}" if pages > 1 else "") + ")\n"
        f"🔵 {online_count} آنلاین   🔴 {total - online_count} آفلاین\n"
        "روی هر اکانت بزن:"
    )


@router.message(F.text == "📶 وضعیت سرویس من")
async def status(message: Message):
    clients = db.get_clients_for_user(message.from_user.id)
    if not clients:
        await message.answer("هنوز سرویس فعالی نداری. از منو «🛒 خرید سرویس» رو بزن.")
        return
    xui = XUIClient()
    kb, online_count = _accounts_keyboard(xui, clients, 0)
    await message.answer(_status_header(len(clients), 0, online_count), reply_markup=kb)


@router.callback_query(F.data.startswith("acc:page:"))
async def status_page(callback: CallbackQuery):
    page = int(callback.data.split(":", 2)[2])
    clients = db.get_clients_for_user(callback.from_user.id)
    if not clients:
        await callback.answer("سرویسی پیدا نشد.", show_alert=True)
        return
    xui = XUIClient()
    kb, online_count = _accounts_keyboard(xui, clients, page)
    await callback.message.edit_text(_status_header(len(clients), page, online_count), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("acc:view:"))
async def status_view(callback: CallbackQuery):
    email = callback.data.split(":", 2)[2]
    clients = db.get_clients_for_user(callback.from_user.id)
    match = next((c for c in clients if c["xui_email"] == email), None)
    if not match:
        await callback.answer("این اکانت پیدا نشد.", show_alert=True)
        return

    xui = XUIClient()
    traffic = xui.get_client_traffic(email) or {}
    used = traffic.get("up", 0) + traffic.get("down", 0)
    enable = traffic.get("enable", True)
    online = email in xui.get_online_emails()
    label = db.get_labels([email]).get(email)

    total_bytes = match["gb"] * 1024**3 if match["gb"] else 0
    vol_lines = (
        ["حجم کل: نامحدود"] if not total_bytes else
        [f"حجم کل: {_fmt_size_en(total_bytes)}",
         f"حجم مصرف‌شده: {_fmt_size_en(used)}",
         f"حجم باقی‌مانده: {_fmt_size_en(max(0, total_bytes - used))}"]
    )
    lines = [f"📄 {escape_markdown(label or email)}", "ـــــــــــــــــــ", f"شناسه اکانت: {escape_markdown(email)}"]
    if label:
        lines.append(f"اسم دلخواه: {escape_markdown(label)}")
    lines += [
        f"اتصال: {'🔵 آنلاین' if online else '🔴 آفلاین'}",
        f"وضعیت: {'✅ فعال' if enable else '🔒 مسدود'}",
        *vol_lines,
        f"زمان باقی‌مانده: {_remaining_time(match['expiry_time'])}",
        f"یوزرنیم اپ: {escape_markdown(email)}",
    ]
    try:
        sub_url = xui.get_sub_url(email)
    except Exception:
        sub_url = ""
    if sub_url:
        lines.append(f"لینک اشتراک:\n{sub_url}")
    if match["uuid"]:
        # Markdown, not HTML: the vless link's query string is full of
        # unescaped "&", which HTML mode would reject as broken entities.
        link = xui.build_vless_link(match["uuid"], email)
        lines.append(f"\n📎 [اتصال خودکار به {config.APP_NAME}]({app_connect_link(link)})")
    text = "\n".join(lines)

    rows = []
    rows.append([InlineKeyboardButton(text=f"⬇️ دانلود {config.APP_NAME}", url=config.APP_DOWNLOAD_URL)])
    rows.append([InlineKeyboardButton(text="🔁 تمدید همین اکانت", callback_data=f"renewpick:{email}")])
    rows.append([InlineKeyboardButton(text="🔄 دریافت لینک", callback_data=f"acc:link:{email}"),
                 InlineKeyboardButton(text="✏️ تغییر اسم", callback_data=f"acc:rename:{email}")])
    rows.append([InlineKeyboardButton(text="◀️ برگشت به لیست", callback_data="acc:page:0")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("acc:link:"))
async def status_send_link(callback: CallbackQuery):
    email = callback.data.split(":", 2)[2]
    clients = db.get_clients_for_user(callback.from_user.id)
    match = next((c for c in clients if c["xui_email"] == email), None)
    if not match:
        await callback.answer("این اکانت پیدا نشد.", show_alert=True)
        return
    xui = XUIClient()
    try:
        link = xui.build_vless_link(match["uuid"], email)
        sub_url = xui.get_sub_url(email)
    except Exception:
        log.exception("failed to rebuild link for %s", email)
        await callback.answer("خطا در ساخت لینک.", show_alert=True)
        return
    await callback.answer()
    label = db.get_labels([email]).get(email)
    await send_service_pack(callback.message, email, link, sub_url, header=f"لینک «{label or email}»:")


@router.callback_query(F.data.startswith("acc:rename:"))
async def status_rename_prompt(callback: CallbackQuery):
    email = callback.data.split(":", 2)[2]
    _RENAME_WAIT[callback.from_user.id] = email
    await callback.message.answer(f"اسم دلخواه جدید برای «{email}» رو بفرست (حداکثر ۴۰ کاراکتر):")
    await callback.answer()


def _is_renaming(message: Message) -> bool:
    return bool(message.text) and message.from_user.id in _RENAME_WAIT


@router.message(_is_renaming)
async def status_rename_apply(message: Message):
    email = _RENAME_WAIT.pop(message.from_user.id)
    owns = any(c["xui_email"] == email for c in db.get_clients_for_user(message.from_user.id))
    if not owns:
        await message.answer("این اکانت مال حساب تو نیست.")
        return
    label = message.text.strip()[:40]
    db.set_label(email, label)
    await message.answer(f"✅ اسم اکانت به «{label}» تغییر کرد.")


@router.message(F.text == "♻️ دریافت دوباره لینک")
async def resend_link(message: Message, bot: Bot):
    clients = db.get_clients_for_user(message.from_user.id)
    if not clients:
        await message.answer("سرویس فعالی برای شما پیدا نشد.")
        return

    if _resend_abuse(message.from_user.id):
        xui = XUIClient()
        for c in clients:
            try:
                xui.set_client_enabled(c["xui_email"], False)
            except Exception:
                log.exception("failed to disable %s after resend abuse", c["xui_email"])
        await message.answer(
            "به‌خاطر استفاده‌ی غیرعادی از این دکمه (چند بار پشت‌سرهم توی یه ساعت)، "
            "سرویس‌هات موقتاً مسدود شدن تا بررسی بشه.\n"
            f"اگه اشتباهی بوده، با پشتیبانی تماس بگیر: {config.SUPPORT_USERNAME}"
        )
        for admin_id in config.ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🚨 هشدار سوءاستفاده: tg:{message.from_user.id} بیش از {RESEND_LIMIT} بار توی یک ساعت "
                    "روی «دریافت دوباره لینک» زده و اکانت‌هاش خودکار مسدود شدن.\n"
                    "برای رفع مسدودیت: 🔒 مسدود/فعال کلاینت",
                )
            except Exception:
                log.exception("failed to alert admin %s about resend abuse", admin_id)
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
