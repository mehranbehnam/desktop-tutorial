"""The all-purpose maintenance menu for @iranvpndeveloper_bot.

Every /command in ops.py is wrapped as a button here, plus capabilities that
previously needed an SSH session or a manual panel click: changing the
Reality dest/SNI, toggling the inbound, server resource stats, a database
backup, broadcasting to users, and per-client extend/disable/delete. The
goal is that nothing about running the service is blocked on a human being
available to type a command by hand.

Multi-step actions (the ones that need a follow-up value, like "which
email?") use a small per-admin pending-action dict instead of aiogram FSM —
there's only ever one flow in flight per admin, so a full state machine
would be overhead without upside.
"""
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup

import config
import db
from handlers import ops
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)

# One pending multi-step action per admin: {tg_id: {"action": ..., ...}}
_pending: dict[int, dict] = {}


def _admin(message: Message) -> bool:
    return message.from_user.id in config.ADMIN_IDS


MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔎 بررسی کامل"), KeyboardButton(text="👥 کلاینت‌ها")],
        [KeyboardButton(text="🛠 اصلاح Flow"), KeyboardButton(text="🔑 اصلاح کلیدها")],
        [KeyboardButton(text="🧪 تست تونل"), KeyboardButton(text="♻️ ری‌استارت Xray")],
        [KeyboardButton(text="⬆️ آپدیت کد"), KeyboardButton(text="🆔 شناسایی پردازش")],
        [KeyboardButton(text="🌐 تغییر دامنه Reality"), KeyboardButton(text="🔌 فعال/غیرفعال اینباند")],
        [KeyboardButton(text="💻 وضعیت سرور"), KeyboardButton(text="💾 بکاپ دیتابیس")],
        [KeyboardButton(text="📊 آمار کلی"), KeyboardButton(text="🧾 سفارش‌های اخیر")],
        [KeyboardButton(text="📢 پیام همگانی"), KeyboardButton(text="🗑 حذف کلاینت")],
        [KeyboardButton(text="⏳ تمدید کلاینت"), KeyboardButton(text="🚫 غیرفعال‌سازی کلاینت")],
        [KeyboardButton(text="📖 راهنما")],
    ],
    resize_keyboard=True,
)

HELP = (
    "🤖 ربات توسعه‌دهنده iranvpn — همه‌ی کارهای نگهداری از همین‌جا:\n\n"
    "هر دکمه‌ی زیر معادل یک کار نگهداری‌ست؛ نیازی به SSH یا پنل نیست.\n"
    "برای لغو یک عملیات چندمرحله‌ای (مثل تغییر دامنه یا حذف کلاینت) هر وقت خواستی /cancel بفرست."
)


@router.error()
async def report_crashes(event):
    """Mirrors ops.py's handler: an admin command must never fail silently."""
    log.exception("unhandled error in devmenu handler", exc_info=event.exception)
    update = event.update
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg and msg.chat.id in config.ADMIN_IDS:
        try:
            await msg.answer(f"❌ خطای پیش‌بینی‌نشده: {type(event.exception).__name__}: {event.exception}")
        except Exception:
            pass
    return True


@router.message(Command("start", "menu"))
async def show_menu(message: Message):
    if not _admin(message):
        await message.answer("این ربات فقط برای مدیر سرویس است.")
        return
    await message.answer(HELP, reply_markup=MENU)


@router.message(Command("cancel"))
async def cancel(message: Message):
    if not _admin(message):
        return
    had = _pending.pop(message.from_user.id, None)
    await message.answer("لغو شد." if had else "چیزی برای لغو نبود.")


# ---------------------------------------------------------------- existing
# commands from ops.py, wrapped as buttons — same handlers, no duplicated
# logic, so a fix there is a fix here too.

@router.message(F.text == "🔎 بررسی کامل")
async def btn_diag(message: Message):
    await ops.diag(message)


@router.message(F.text == "👥 کلاینت‌ها")
async def btn_clients(message: Message):
    await ops.clients_cmd(message)


@router.message(F.text == "🛠 اصلاح Flow")
async def btn_fixflow(message: Message):
    await ops.fixflow(message)


@router.message(F.text == "🔑 اصلاح کلیدها")
async def btn_fixkeys(message: Message):
    await ops.fixkeys(message)


@router.message(F.text == "🧪 تست تونل")
async def btn_testtunnel(message: Message):
    await ops.testtunnel(message)


@router.message(F.text == "♻️ ری‌استارت Xray")
async def btn_restart_xray(message: Message):
    await ops.restart_xray(message)


@router.message(F.text == "⬆️ آپدیت کد")
async def btn_update(message: Message):
    await ops.update(message)


@router.message(F.text == "🆔 شناسایی پردازش")
async def btn_whoami(message: Message):
    await ops.whoami(message)


@router.message(F.text == "📖 راهنما")
async def btn_help(message: Message):
    if not _admin(message):
        return
    await message.answer(HELP + "\n\n" + ops.HELP)


# ---------------------------------------------------------------- new: Reality dest/SNI

@router.message(F.text == "🌐 تغییر دامنه Reality")
async def ask_new_dest(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "change_dest"}
    await message.answer(
        "دامنه‌ی جدید Reality رو بفرست (بدون https و بدون پورت)، مثلاً:\n"
        "www.digikala.com\n\n"
        "این دامنه هم SNI و هم مقصد fallback می‌شود. /cancel برای لغو."
    )


async def _apply_new_dest(message: Message, new_host: str):
    new_host = new_host.strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not new_host or " " in new_host:
        await message.answer("دامنه‌ی نامعتبر. دوباره از دکمه‌ی 🌐 شروع کن.")
        return
    x = XUIClient()
    try:
        inbound = x.get_inbound()
        stream = inbound.get("streamSettings")
        stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
        reality = stream.get("realitySettings") or {}
        reality["dest"] = f"{new_host}:443"
        reality["serverNames"] = [new_host]
        stream["realitySettings"] = reality
        body = {
            "enable": inbound.get("enable", True),
            "remark": inbound.get("remark", ""),
            "listen": inbound.get("listen", ""),
            "port": inbound.get("port"),
            "protocol": inbound.get("protocol"),
            "expiryTime": inbound.get("expiryTime", 0),
            "total": inbound.get("total", 0),
            "settings": json.loads(inbound["settings"]) if isinstance(inbound.get("settings"), str)
            else inbound.get("settings", {}),
            "streamSettings": stream,
            "sniffing": json.loads(inbound["sniffing"]) if isinstance(inbound.get("sniffing"), str)
            else inbound.get("sniffing", {}),
        }
        x._request("POST", f"/panel/api/inbounds/update/{inbound['id']}", json=body)
        x._request("POST", "/panel/api/server/restartXrayService")
        await message.answer(
            f"✅ دامنه‌ی Reality به {new_host} تغییر کرد و Xray ری‌استارت شد.\n"
            "با 🧪 تست تونل نتیجه رو بررسی کن."
        )
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ ناموفق: {e}")


# ---------------------------------------------------------------- new: enable/disable inbound

@router.message(F.text == "🔌 فعال/غیرفعال اینباند")
async def toggle_inbound(message: Message):
    if not _admin(message):
        return
    x = XUIClient()
    try:
        inbound = x.get_inbound()
        new_state = not inbound.get("enable", True)
        stream = inbound.get("streamSettings")
        stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
        body = {
            "enable": new_state,
            "remark": inbound.get("remark", ""),
            "listen": inbound.get("listen", ""),
            "port": inbound.get("port"),
            "protocol": inbound.get("protocol"),
            "expiryTime": inbound.get("expiryTime", 0),
            "total": inbound.get("total", 0),
            "settings": json.loads(inbound["settings"]) if isinstance(inbound.get("settings"), str)
            else inbound.get("settings", {}),
            "streamSettings": stream,
            "sniffing": json.loads(inbound["sniffing"]) if isinstance(inbound.get("sniffing"), str)
            else inbound.get("sniffing", {}),
        }
        x._request("POST", f"/panel/api/inbounds/update/{inbound['id']}", json=body)
        state_fa = "فعال" if new_state else "غیرفعال"
        await message.answer(f"✅ اینباند {state_fa} شد.")
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ ناموفق: {e}")


# ---------------------------------------------------------------- new: server resources

@router.message(F.text == "💻 وضعیت سرور")
async def server_status(message: Message):
    if not _admin(message):
        return
    lines = []
    try:
        load1, load5, load15 = os.getloadavg()
        lines.append(f"بار سیستم: {load1:.2f} / {load5:.2f} / {load15:.2f} (۱ / ۵ / ۱۵ دقیقه)")
    except OSError:
        pass
    try:
        total, used, free = shutil.disk_usage("/")
        lines.append(f"دیسک: {used / 1024**3:.1f} از {total / 1024**3:.1f} گیگ استفاده‌شده "
                     f"({used / total * 100:.0f}%)")
    except OSError as e:
        lines.append(f"دیسک: قابل بررسی نبود ({e})")
    try:
        with open("/proc/meminfo") as fh:
            mem = {}
            for line in fh:
                key, _, rest = line.partition(":")
                mem[key] = int(rest.strip().split()[0])  # kB
        total_mb = mem.get("MemTotal", 0) / 1024
        avail_mb = mem.get("MemAvailable", 0) / 1024
        used_mb = total_mb - avail_mb
        lines.append(f"رم: {used_mb:.0f} از {total_mb:.0f} مگ استفاده‌شده ({used_mb / total_mb * 100:.0f}%)")
    except (OSError, ZeroDivisionError, ValueError):
        lines.append("رم: قابل بررسی نبود")
    try:
        with open("/proc/uptime") as fh:
            up_seconds = float(fh.read().split()[0])
        days = up_seconds / 86400
        lines.append(f"آپ‌تایم سرور: {days:.1f} روز")
    except (OSError, ValueError):
        pass
    await message.answer("💻 وضعیت سرور:\n\n" + "\n".join(lines))


# ---------------------------------------------------------------- new: database backup

@router.message(F.text == "💾 بکاپ دیتابیس")
async def backup_db(message: Message):
    if not _admin(message):
        return
    await message.answer("⏳ در حال گرفتن بکاپ سازگار از دیتابیس…")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest_path = os.path.join(tmp, f"bot-backup-{int(time.time())}.db")
            src = sqlite3.connect(config.DB_PATH)
            dst = sqlite3.connect(dest_path)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            await message.answer_document(FSInputFile(dest_path), caption="💾 بکاپ دیتابیس")
    except Exception as e:
        await message.answer(f"❌ گرفتن بکاپ ناموفق بود: {type(e).__name__}: {e}")


# ---------------------------------------------------------------- new: stats + orders

@router.message(F.text == "📊 آمار کلی")
async def stats_cmd(message: Message):
    if not _admin(message):
        return
    s = db.stats()
    await message.answer(
        "📊 آمار کلی:\n\n"
        f"کاربران: {s['users']}\n"
        f"تست‌های استفاده‌شده: {s['trial_used']}\n"
        f"کلاینت‌های ساخته‌شده: {s['clients']}\n"
        f"سفارش‌های تاییدشده: {s['orders_approved']} — جمع {s['revenue_total']:,} تومان\n"
        f"سفارش‌های در انتظار بررسی: {s['orders_pending']}"
    )


@router.message(F.text == "🧾 سفارش‌های اخیر")
async def recent_orders_cmd(message: Message):
    if not _admin(message):
        return
    orders = db.recent_orders(10)
    if not orders:
        await message.answer("هنوز سفارشی ثبت نشده.")
        return
    lines = []
    for o in orders:
        lines.append(f"#{o['id']} — {o['plan_key']} — {o['amount']:,} تومان — {o['status']} — tg:{o['tg_id']}")
    await message.answer("🧾 ۱۰ سفارش اخیر:\n\n" + "\n".join(lines))


# ---------------------------------------------------------------- new: broadcast

@router.message(F.text == "📢 پیام همگانی")
async def ask_broadcast(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "broadcast"}
    await message.answer("متن پیامی که برای همه‌ی کاربران ارسال بشه رو بفرست. /cancel برای لغو.")


async def _do_broadcast(message: Message, text: str):
    ids = db.all_user_ids()
    sent, failed = 0, 0
    status_msg = await message.answer(f"⏳ در حال ارسال به {len(ids)} کاربر…")
    for tg_id in ids:
        try:
            await message.bot.send_message(tg_id, text)
            sent += 1
        except Exception:
            failed += 1
    await status_msg.edit_text(f"✅ ارسال شد: {sent} موفق، {failed} ناموفق (بلاک یا حذف‌شده).")


# ---------------------------------------------------------------- new: per-client actions

@router.message(F.text == "🗑 حذف کلاینت")
async def ask_delete_client(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "delete_client"}
    await message.answer("ایمیل کلاینتی که باید حذف بشه رو بفرست (مثل 👥 کلاینت‌ها می‌بینی). /cancel برای لغو.")


async def _do_delete_client(message: Message, email: str):
    x = XUIClient()
    try:
        x.delete_client(inbound_id=config.XUI_INBOUND_ID, client_uuid="", email=email)
        await message.answer(f"✅ کلاینت {email} حذف شد.")
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")


@router.message(F.text == "🚫 غیرفعال‌سازی کلاینت")
async def ask_disable_client(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "disable_client"}
    await message.answer("ایمیل کلاینتی که باید غیرفعال بشه رو بفرست. /cancel برای لغو.")


async def _do_disable_client(message: Message, email: str):
    x = XUIClient()
    traffic = x.get_client_traffic(email)
    if not traffic:
        await message.answer(f"کلاینتی با ایمیل {email} پیدا نشد.")
        return
    body = {"email": email, "totalGB": traffic.get("total", 0),
            "expiryTime": traffic.get("expiryTime", 0), "enable": False}
    flow = x.client_flow()
    if flow:
        body["flow"] = flow
    try:
        x._request("POST", f"/panel/api/clients/update/{email}", json=body)
        await message.answer(f"✅ کلاینت {email} غیرفعال شد.")
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")


@router.message(F.text == "⏳ تمدید کلاینت")
async def ask_extend_client(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "extend_client", "stage": "email"}
    await message.answer("ایمیل کلاینتی که باید تمدید بشه رو بفرست. /cancel برای لغو.")


async def _do_extend_client(message: Message, email: str, days: int):
    x = XUIClient()
    traffic = x.get_client_traffic(email)
    if not traffic:
        await message.answer(f"کلاینتی با ایمیل {email} پیدا نشد.")
        return
    now_ms = int(time.time() * 1000)
    cur_expiry = traffic.get("expiryTime", 0)
    base = cur_expiry if cur_expiry and cur_expiry > now_ms else now_ms
    new_expiry = base + days * 86400 * 1000
    body = {"email": email, "totalGB": traffic.get("total", 0), "expiryTime": new_expiry, "enable": True}
    flow = x.client_flow()
    if flow:
        body["flow"] = flow
    try:
        x._request("POST", f"/panel/api/clients/update/{email}", json=body)
        await message.answer(f"✅ کلاینت {email} به مدت {days} روز تمدید شد.")
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")


# ---------------------------------------------------------------- pending-action dispatch
# Only fires when this admin has an open multi-step flow — everything else
# (including menu button text that doesn't match) falls through untouched
# because this handler is filtered out, not because it swallows and ignores.

def _has_pending(message: Message) -> bool:
    return bool(message.text) and not message.text.startswith("/") and message.from_user.id in _pending


@router.message(_has_pending)
async def handle_pending(message: Message):
    pending = _pending.pop(message.from_user.id)
    action = pending["action"]
    text = message.text.strip()

    if action == "change_dest":
        await _apply_new_dest(message, text)
    elif action == "broadcast":
        await _do_broadcast(message, message.text)
    elif action == "delete_client":
        await _do_delete_client(message, text)
    elif action == "disable_client":
        await _do_disable_client(message, text)
    elif action == "extend_client":
        if pending["stage"] == "email":
            _pending[message.from_user.id] = {"action": "extend_client", "stage": "days", "email": text}
            await message.answer("چند روز تمدید بشه؟ فقط عدد بفرست.")
        else:
            try:
                days = int(text)
            except ValueError:
                await message.answer("عدد نامعتبر. از 🔁 دوباره شروع کن.")
                return
            await _do_extend_client(message, pending["email"], days)
