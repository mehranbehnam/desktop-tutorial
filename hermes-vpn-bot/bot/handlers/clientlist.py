"""Shared client list: a paginated inline-button picker showing every
client's live status at a glance — 🔵 online, 🔴 offline, 🔒 blocked — with
tap-to-filter search. Used by both bots (via /clients and, on the developer
bot, the "👥 کلاینت‌ها" / "🔍 وضعیت کلاینت" buttons) so there is exactly one
implementation to fix instead of two menus quietly drifting apart.
"""
import json
import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)

PAGE_SIZE = 10
# tg_id -> {"emails": [...]} — the current (possibly search-filtered) list
# this admin is paging through.
_pending: dict[int, dict] = {}


def _admin(obj) -> bool:
    return obj.from_user.id in config.ADMIN_IDS


def _size(n: int) -> str:
    return f"{n / 1024**3:.2f}GB" if n >= 1024**3 else f"{n / 1024**2:.0f}MB"


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


def _header(total: int, page: int) -> str:
    start = page * PAGE_SIZE
    shown = max(0, min(PAGE_SIZE, total - start))
    return (f"👥 لیست کلاینت‌ها ({shown} از {total})\n\n"
            "روی هر کدوم بزن تا وضعیتش رو ببینی، یا اسمی رو تایپ کن تا جستجو کنم.")


async def show_list(message: Message):
    """Entry point — call this from any "list clients" button/command."""
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
    _pending[message.from_user.id] = {"emails": emails}
    await message.answer(_header(len(emails), 0), reply_markup=_keyboard(x, emails, 0))


@router.message(Command("clients"))
async def clients_command(message: Message):
    await show_list(message)


def _searching(message: Message) -> bool:
    return bool(message.text) and not message.text.startswith("/") and message.from_user.id in _pending


@router.message(_searching)
async def search_clients(message: Message):
    query = message.text.strip().lower()
    x = XUIClient()
    try:
        all_emails = [c.get("email", "?") for c in _list_clients(x)]
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خطا: {e}")
        return
    matched = [e for e in all_emails if query in e.lower()] if query else all_emails
    if not matched:
        await message.answer("چیزی با این اسم پیدا نشد — دوباره امتحان کن.")
        return
    _pending[message.from_user.id] = {"emails": matched}
    await message.answer(_header(len(matched), 0), reply_markup=_keyboard(x, matched, 0))


@router.callback_query(F.data.startswith("cl:pg:"))
async def page_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending:
        await callback.answer("این لیست دیگه معتبر نیست — دوباره /clients بزن.", show_alert=True)
        return
    page = int(callback.data.split(":", 2)[2])
    x = XUIClient()
    emails = pending["emails"]
    await callback.message.edit_text(_header(len(emails), page), reply_markup=_keyboard(x, emails, page))
    await callback.answer()


@router.callback_query(F.data.startswith("cl:p:"))
async def pick_button(callback: CallbackQuery):
    if not _admin(callback):
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending:
        await callback.answer("این لیست دیگه معتبر نیست — دوباره /clients بزن.", show_alert=True)
        return
    emails = pending["emails"]
    idx = int(callback.data.split(":", 2)[2])
    if idx < 0 or idx >= len(emails):
        await callback.answer("این کلاینت دیگه تو لیست نیست.", show_alert=True)
        return
    _pending.pop(callback.from_user.id, None)
    await callback.answer()
    await show_detail(callback.message, emails[idx])


async def show_detail(message: Message, email: str):
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t:
        await message.answer(f"کلاینتی با ایمیل {email} پیدا نشد.")
        return
    exp = t.get("expiryTime", 0)
    exp_str = "بدون انقضا" if not exp else time.strftime("%Y-%m-%d %H:%M", time.localtime(exp / 1000))
    total = t.get("total", 0)
    used = t.get("up", 0) + t.get("down", 0)
    online = email in x.get_online_emails()
    enabled = t.get("enable", True)
    conn = "🔒 مسدود" if not enabled else ("🔵 آنلاین" if online else "🔴 آفلاین")
    await message.answer(
        f"🔍 {email}\n"
        f"اتصال: {conn}\n"
        f"مصرف: {_size(used)} از {_size(total) if total else 'نامحدود'}\n"
        f"انقضا: {exp_str}\n"
        f"فعال: {'بله' if enabled else 'خیر'}"
    )
