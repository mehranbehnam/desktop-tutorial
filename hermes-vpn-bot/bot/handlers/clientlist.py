"""Shared client list: a paginated inline-button picker showing every
client's live status at a glance — 🔵 online, 🔴 offline, 🔒 blocked — with
tap-to-filter search, and a detail card (Hermes-style layout) with buttons
to connect, renew, resend the link, or rename. Used by both bots (via
/clients and, on the developer bot, the "👥 کلاینت‌ها" / "🔍 وضعیت کلاینت"
buttons) so there is exactly one implementation to fix instead of two
menus quietly drifting apart.
"""
import datetime
import json
import logging
import time
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from utils.delivery import app_connect_link
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)

PAGE_SIZE = 10
_TEHRAN_TZ = ZoneInfo("Asia/Tehran")
# tg_id -> current multi-step state. "mode" is "list" (browsing/searching
# the picker), "rename" or "renew" (a follow-up value is expected next).
# A "list" entry may also carry "list_action" ("delete"/"toggle") when the
# picker was opened from 🗑 حذف کلاینت / 🔒 مسدود/فعال کلاینت instead of
# 👥 کلاینت‌ها — tapping a client then performs that action instead of
# opening its detail card.
_pending: dict[int, dict] = {}

_ACTION_META = {
    "delete": ("کدوم کلاینت رو پاک کنم؟", "روی یکی بزن تا پاکش کنم، یا اسمی رو تایپ کن تا جستجو کنم."),
    "toggle": ("کدوم کلاینت رو مسدود/فعال کنم؟", "روی یکی بزن تا وضعیتش عوض بشه، یا اسمی رو تایپ کن تا جستجو کنم."),
}


def _admin(obj) -> bool:
    return obj.from_user.id in config.ADMIN_IDS


def _size(n: int) -> str:
    """GB/MB, no trailing ".00" on a round number — "20GB" reads cleaner
    than "20.00GB" on the detail card."""
    n = max(0, n or 0)
    if n < 1024**3:
        return f"{n / 1024**2:.0f}MB"
    gb = n / 1024**3
    return f"{gb:.0f}GB" if gb == int(gb) else f"{gb:.2f}GB"


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    j_days_in_month = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    for i in range(gm2):
        g_day_no += g_days_in_month[i]
    if gm2 > 1 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    g_day_no += gd2
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    jm, jd = 12, j_day_no + 1
    for i in range(11):
        if j_day_no < j_days_in_month[i]:
            jm, jd = i + 1, j_day_no + 1
            break
        j_day_no -= j_days_in_month[i]
    return jy, jm, jd


def _format_jalali(ts: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts, _TEHRAN_TZ)
    jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{dt.strftime('%H:%M')} {jy:04d}/{jm:02d}/{jd:02d}"


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


def _list_clients(x: XUIClient) -> list[dict]:
    inbound = x.get_inbound()
    settings = inbound.get("settings")
    settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
    return settings.get("clients") or []


def _dot(email: str, online: set[str], clients_by_email: dict) -> str:
    enabled = clients_by_email.get(email, {}).get("enable", True)
    if not enabled:
        return "🔒"
    return "🔵" if email in online else "🔴"


def _keyboard(x: XUIClient, emails: list[str], page: int) -> InlineKeyboardMarkup:
    clients_by_email = {c.get("email"): c for c in _list_clients(x)}
    online = x.get_online_emails()
    start = page * PAGE_SIZE
    chunk = list(enumerate(emails))[start:start + PAGE_SIZE]
    rows, row = [], []
    for idx, email in chunk:
        row.append(InlineKeyboardButton(text=f"{_dot(email, online, clients_by_email)} {email}",
                                         callback_data=f"cl:p:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"cl:pg:{page-1}"))
    if start + PAGE_SIZE < len(emails):
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"cl:pg:{page+1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _header(total: int, page: int, title: str, hint: str) -> str:
    start = page * PAGE_SIZE
    shown = max(0, min(PAGE_SIZE, total - start))
    return f"{title} ({shown} از {total})\n\n{hint}"


def _header_for(pending: dict, total: int, page: int) -> str:
    action = pending.get("list_action")
    if action in _ACTION_META:
        title, hint = _ACTION_META[action]
    else:
        title = "👥 لیست کلاینت‌ها"
        hint = "روی هر کدوم بزن تا وضعیتش رو ببینی، یا اسمی رو تایپ کن تا جستجو کنم."
    return _header(total, page, title, hint)


def _blocked_line(x: XUIClient, email: str) -> str:
    label = db.get_labels([email]).get(email)
    t = x.get_client_traffic(email) or {}
    total = t.get("total", 0)
    used = t.get("up", 0) + t.get("down", 0)
    size_txt = "نامحدود" if not total else f"{_size(used)}/{_size(total)}"
    remain = _remaining_time(t.get("expiryTime", 0))
    return f"🔒 {label or email}: {size_txt} • {remain}"


def _blocked_keyboard(emails: list[str], page: int) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    chunk = list(enumerate(emails))[start:start + PAGE_SIZE]
    rows, row = [], []
    for idx, email in chunk:
        label = db.get_labels([email]).get(email)
        row.append(InlineKeyboardButton(text=f"🔒 {label or email}", callback_data=f"cl:p:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"cl:pg:{page-1}"))
    if start + PAGE_SIZE < len(emails):
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"cl:pg:{page+1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_list(pending: dict, page: int, x: XUIClient) -> tuple[str, InlineKeyboardMarkup]:
    """Builds the (text, keyboard) pair for whichever picker mode `pending`
    is in — plain browse, delete/toggle action list, or the blocked-only
    view (which shows a GB/days line per client instead of just a dot)."""
    emails = pending["emails"]
    if pending.get("blocked"):
        start = page * PAGE_SIZE
        chunk = emails[start:start + PAGE_SIZE]
        total_pages = max(1, (len(emails) + PAGE_SIZE - 1) // PAGE_SIZE)
        lines = [f"🔒 کلاینت‌های مسدود — صفحه {page + 1} از {total_pages} (کل: {len(emails)})", ""]
        lines += [_blocked_line(x, email) for email in chunk]
        return "\n".join(lines), _blocked_keyboard(emails, page)
    return _header_for(pending, len(emails), page), _keyboard(x, emails, page)


async def _show_picker(message: Message, action: str | None):
    """Shared entry point for both the plain browse list and the
    delete/toggle action pickers — same paginated UI either way."""
    if not _admin(message):
        return
    x = XUIClient()
    try:
        clients = _list_clients(x)
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خطا در خوندن لیست کلاینت‌ها: {e}")
        return
    emails = [c.get("email", "?") for c in clients]
    if not emails:
        await message.answer("هیچ کلاینتی روی اینباند نیست.")
        return
    pending = {"mode": "list", "emails": emails, "page": 0}
    if action:
        pending["list_action"] = action
    _pending[message.from_user.id] = pending
    text, kb = _render_list(pending, 0, x)
    await message.answer(text, reply_markup=kb)


async def show_list(message: Message):
    """Entry point — call this from any "list clients" button/command."""
    await _show_picker(message, None)


async def show_action_list(message: Message, action: str):
    """Entry point for the delete / block-unblock picker (action is
    "delete" or "toggle") — call this from those buttons instead of
    show_list."""
    await _show_picker(message, action)


async def show_blocked_list(message: Message):
    """Entry point for "🔒 لیست مسدودی‌ها" — every currently-disabled
    client, each with its GB usage and remaining time, paginated the same
    way as the other pickers. Tapping one opens its detail card, which now
    carries an unblock button."""
    if not _admin(message):
        return
    x = XUIClient()
    try:
        clients = _list_clients(x)
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خطا در خوندن لیست کلاینت‌ها: {e}")
        return
    emails = [c.get("email", "?") for c in clients if not c.get("enable", True)]
    if not emails:
        await message.answer("هیچ کلاینت مسدودی نیست ✅")
        return
    pending = {"mode": "list", "emails": emails, "page": 0, "blocked": True}
    _pending[message.from_user.id] = pending
    text, kb = _render_list(pending, 0, x)
    await message.answer(text, reply_markup=kb)


@router.message(Command("clients"))
async def clients_command(message: Message):
    await show_list(message)


def _has_pending(message: Message) -> bool:
    return bool(message.text) and not message.text.startswith("/") and message.from_user.id in _pending


@router.message(_has_pending)
async def handle_pending(message: Message):
    pending = _pending[message.from_user.id]
    mode = pending.get("mode", "list")
    if mode == "rename":
        await _rename_step(message, pending)
    elif mode == "renew":
        await _renew_step(message, pending)
    else:
        await _search_step(message, pending)


async def _search_step(message: Message, pending: dict):
    query = message.text.strip().lower()
    x = XUIClient()
    try:
        clients = _list_clients(x)
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خطا: {e}")
        return
    if pending.get("blocked"):
        all_emails = [c.get("email", "?") for c in clients if not c.get("enable", True)]
    else:
        all_emails = [c.get("email", "?") for c in clients]
    matched = [e for e in all_emails if query in e.lower()] if query else all_emails
    if not matched:
        await message.answer("چیزی با این اسم پیدا نشد — دوباره امتحان کن.")
        return
    new_pending = {"mode": "list", "emails": matched, "page": 0}
    if pending.get("list_action"):
        new_pending["list_action"] = pending["list_action"]
    if pending.get("blocked"):
        new_pending["blocked"] = True
    _pending[message.from_user.id] = new_pending
    text, kb = _render_list(new_pending, 0, x)
    await message.answer(text, reply_markup=kb)


async def _rename_step(message: Message, pending: dict):
    email = pending["email"]
    label = message.text.strip()[:40]
    _pending.pop(message.from_user.id, None)
    db.set_label(email, label)
    await message.answer(f"✅ اسم «{email}» به «{label}» تغییر کرد.")
    await show_detail(message, email)


async def _renew_step(message: Message, pending: dict):
    email = pending["email"]
    try:
        days = int(message.text.strip())
    except ValueError:
        await message.answer("عدد نامعتبر — فقط تعداد روز رو بفرست، یا /cancel بزن.")
        return
    _pending.pop(message.from_user.id, None)
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t:
        await message.answer(f"کلاینتی با ایمیل {email} پیدا نشد.")
        return
    now_ms = int(time.time() * 1000)
    cur_exp = t.get("expiryTime", 0)
    base = cur_exp if cur_exp and cur_exp > now_ms else now_ms
    body = {"email": email, "totalGB": t.get("total", 0), "expiryTime": base + days * 86400 * 1000, "enable": True}
    flow = x.client_flow()
    if flow:
        body["flow"] = flow
    try:
        x._request("POST", f"/panel/api/clients/update/{email}", json=body)
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")
        return
    await message.answer(f"✅ {email} به مدت {days} روز تمدید شد.")
    await show_detail(message, email)


@router.callback_query(F.data.startswith("cl:pg:"))
async def page_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending or "emails" not in pending:
        await callback.answer("این لیست دیگه معتبر نیست — دوباره امتحان کن.", show_alert=True)
        return
    page = int(callback.data.split(":", 2)[2])
    pending["page"] = page
    x = XUIClient()
    text, kb = _render_list(pending, page, x)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("cl:p:"))
async def pick_button(callback: CallbackQuery):
    """Tapping any client, in any picker (plain browse, the delete/toggle
    action lists, or the blocked-only view), always opens its full detail
    card — the card itself carries the delete/block buttons, each with its
    own confirm step, so every entry point converges on the same complete,
    accurate view instead of a shortcut action list."""
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending or "emails" not in pending:
        await callback.answer("این لیست دیگه معتبر نیست — دوباره امتحان کن.", show_alert=True)
        return
    emails = pending["emails"]
    idx = int(callback.data.split(":", 2)[2])
    if idx < 0 or idx >= len(emails):
        await callback.answer("این کلاینت دیگه تو لیست نیست.", show_alert=True)
        return
    email = emails[idx]
    _pending.pop(callback.from_user.id, None)
    await callback.answer()
    await show_detail(callback.message, email)


@router.callback_query(F.data == "cl:back")
async def back_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    await callback.answer()
    await show_list(callback.message)


@router.callback_query(F.data.startswith("cl:link:"))
async def link_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t or not t.get("uuid"):
        await callback.answer("این کلاینت پیدا نشد.", show_alert=True)
        return
    try:
        link = x.build_vless_link(t["uuid"], email)
        sub_url = x.get_sub_url(email)
    except Exception as e:
        await callback.answer(f"{type(e).__name__}: {e}", show_alert=True)
        return
    await callback.answer()
    text = f"🔗 لینک «{email}»:\n\n<code>{link}</code>"
    if sub_url:
        text += f"\n\n🔗 لینک سابسکرایب:\n<code>{sub_url}</code>"
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("cl:rename:"))
async def rename_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    _pending[callback.from_user.id] = {"mode": "rename", "email": email}
    await callback.answer()
    await callback.message.answer(f"اسم دلخواه جدید برای «{email}» رو بفرست (حداکثر ۴۰ کاراکتر). /cancel برای لغو.")


@router.callback_query(F.data.startswith("cl:renew:"))
async def renew_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    _pending[callback.from_user.id] = {"mode": "renew", "email": email}
    await callback.answer()
    await callback.message.answer(f"چند روز به «{email}» اضافه بشه؟ فقط عدد بفرست. /cancel برای لغو.")


@router.message(Command("cancel", "stop"))
async def cancel(message: Message):
    if not _admin(message):
        return
    had = _pending.pop(message.from_user.id, None)
    if had:
        await message.answer("لغو شد.")


def _detail_keyboard(email: str, enabled: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🔓 فعال کن" if not enabled else "🔒 مسدود کن",
            callback_data=f"cl:togask:{email}",
        )],
        [InlineKeyboardButton(text="🗑 حذف کلاینت", callback_data=f"cl:delask:{email}")],
        [InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=f"cl:refresh:{email}")],
        [InlineKeyboardButton(text="🔁 تمدید همین اکانت", callback_data=f"cl:renew:{email}"),
         InlineKeyboardButton(text="✏️ تغییر اسم", callback_data=f"cl:rename:{email}")],
        [InlineKeyboardButton(text=f"⬇️ دانلود {config.APP_NAME}", url=config.APP_DOWNLOAD_URL)],
        [InlineKeyboardButton(text="◀️ برگشت به لیست", callback_data="cl:back")],
    ])


@router.callback_query(F.data.startswith("cl:refresh:"))
async def refresh_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    await callback.answer("🔄 به‌روز شد.")
    await show_detail(callback.message, email)


@router.callback_query(F.data.startswith("cl:togask:"))
async def toggle_ask_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t:
        await callback.answer("این کلاینت پیدا نشد.", show_alert=True)
        return
    enabled = t.get("enable", True)
    name = db.get_labels([email]).get(email) or email
    await callback.answer()
    await callback.message.answer(
        f"{name} الان {'فعاله' if enabled else 'مسدوده'} — {'مسدود' if enabled else 'فعال'} بشه؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ تایید", callback_data=f"cl:togyes:{email}"),
            InlineKeyboardButton(text="❌ نفو", callback_data=f"cl:togno:{email}"),
        ]]),
    )


@router.callback_query(F.data.startswith("cl:togyes:"))
async def toggle_confirm_yes(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t:
        await callback.answer("این کلاینت پیدا نشد.", show_alert=True)
        return
    new_state = not t.get("enable", True)
    try:
        x.set_client_enabled(email, new_state)
    except XUIError as e:
        await callback.answer(f"❌ ناموفق: {e}", show_alert=True)
        return
    await callback.answer(f"✅ {'فعال' if new_state else 'مسدود'} شد.")
    await callback.message.delete()
    await show_detail(callback.message, email)


@router.callback_query(F.data.startswith("cl:togno:"))
async def toggle_confirm_no(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    await callback.answer()
    await callback.message.delete()
    await show_detail(callback.message, email)


@router.callback_query(F.data.startswith("cl:delask:"))
async def delete_ask_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    await callback.answer()
    await callback.message.answer(
        f"❗ مطمئنی می‌خوای «{email}» رو کامل پاک کنی؟ این کار قابل برگشت نیست.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ تایید", callback_data=f"cl:delyes:{email}"),
            InlineKeyboardButton(text="❌ نفو", callback_data=f"cl:delno:{email}"),
        ]]),
    )


@router.callback_query(F.data.startswith("cl:delyes:"))
async def delete_confirm_yes(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    x = XUIClient()
    try:
        x.delete_client(inbound_id=config.XUI_INBOUND_ID, client_uuid="", email=email)
    except XUIError as e:
        await callback.answer(f"❌ ناموفق: {e}", show_alert=True)
        return
    await callback.answer("✅ حذف شد.")
    await callback.message.edit_text(f"✅ کلاینت «{email}» حذف شد.")


@router.callback_query(F.data.startswith("cl:delno:"))
async def delete_confirm_no(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    email = callback.data.split(":", 2)[2]
    await callback.answer()
    await callback.message.delete()
    await show_detail(callback.message, email)


async def show_detail(message: Message, email: str):
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t:
        await message.answer(f"کلاینتی با ایمیل {email} پیدا نشد.")
        return
    total = t.get("total", 0)
    used = t.get("up", 0) + t.get("down", 0)
    online = email in x.get_online_emails()
    enabled = t.get("enable", True)
    label = db.get_labels([email]).get(email)

    if online:
        conn_line = "🔵 آنلاین"
    elif used > 0:
        conn_line = "🔴 آفلاین"
    else:
        conn_line = "⚪ هنوز وصل نشده"

    vol_lines = (
        ["حجم کل: نامحدود"] if not total else
        [f"حجم کل: {_size(total)}",
         f"حجم مصرف‌شده: {_size(used)}",
         f"حجم باقی‌مانده: {_size(max(0, total - used))}"]
    )
    lines = [f"<b>{label or email}</b>", f"اتصال: {conn_line}", f"وضعیت: {'✅ فعال' if enabled else '🔒 مسدود'}"]
    lines += vol_lines
    lines.append(f"زمان باقی‌مانده: {_remaining_time(t.get('expiryTime', 0))}")

    record = db.get_client(email)
    if record and record["tg_id"]:
        lines.append(f"مالک تلگرام: {record['tg_id']}")
    if record and record["created_at"]:
        lines.append(f"تاریخ ساخت: {_format_jalali(record['created_at'])}")

    try:
        sub_url = x.get_sub_url(email)
    except Exception:
        sub_url = ""
    if sub_url:
        lines.append(f"لینک اشتراک:\n{sub_url}")

    if t.get("uuid"):
        link = x.build_vless_link(t["uuid"], email)
        lines.append(f'\n📎 <a href="{app_connect_link(link)}">اتصال خودکار به {config.APP_NAME}</a>')

    if not db.has_approved_order(email):
        lines.append("")
        lines.append("خریدی ثبت نشده (احتمالاً دستی ساخته شده).")

    await message.answer("\n".join(lines), reply_markup=_detail_keyboard(email, enabled), parse_mode="HTML")
