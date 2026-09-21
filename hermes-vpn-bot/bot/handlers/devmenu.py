"""The all-purpose maintenance menu for @iranvpndeveloper_bot.

Every /command in ops.py is wrapped as a button here, the sales bot's own
customer-facing flows (buy/trial/renew/status) are reused wholesale so the
business can run entirely from this one bot if needed, and there's a set of
capabilities that previously needed an SSH session or a manual panel click:
changing the Reality dest/SNI, toggling the inbound, repointing the bot at
a different X-UI panel, server resource stats, a database backup,
broadcasting to users, per-client create/extend/disable/delete (single and
bulk), financial reports, and fail2ban ban-list/unban + restarting the
panel itself on the Iran server over SSH.

The SSH-dependent commands only work once an admin has typed the Iran
server's SSH login into this bot via "🔑 تنظیم SSH سرور ایران" — that value
never has to pass through anyone else, including whoever wrote this code.

Multi-step actions (the ones that need a follow-up value, like "which
email?") use a small per-admin pending-action dict instead of aiogram FSM —
there's only ever one flow in flight per admin, so a full state machine
would be overhead without upside. Flows with more than one follow-up value
(e.g. "new panel: URL, then user, then password...") manage their own
stage transitions and are responsible for popping themselves out of
`_pending` on their last step.
"""
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time

import requests

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

import config
import db
from handlers import clientlist, ops
from keyboards import admin_review_keyboard
from utils import iran_ssh, support_relay
from utils.envfile import env_path as _env_path, service_names as _service_names, set_env_var as _set_env_var
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)

# One pending multi-step action per admin: {tg_id: {"action": ..., ...}}
_pending: dict[int, dict] = {}


def _admin(message: Message) -> bool:
    return message.from_user.id in config.ADMIN_IDS


def _size(n: int) -> str:
    return f"{n / 1024**3:.2f}GB" if n >= 1024**3 else f"{n / 1024**2:.0f}MB"


def _list_clients(x: XUIClient) -> list[dict]:
    inbound = x.get_inbound()
    settings = inbound.get("settings")
    settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
    return settings.get("clients") or []


# The menu is organized as top-level categories, each opening its own
# button page — a flat 24-row wall of buttons was unusable on a phone.
# Every action handler below is unchanged; only which keyboard is showing
# when its button gets tapped changes, and Telegram sends the same plain
# text regardless, so nothing about the handlers needed to change.

CAT_CLIENTS = "👥 مدیریت کلاینت‌ها"
CAT_SECURITY = "🔒 امنیت (Fail2ban)"
CAT_MAINTENANCE = "🛠 نگهداری سرور"
CAT_PANEL = "⚙️ تنظیمات پنل و SSH"
CAT_FINANCE = "💰 مالی، آمار و کاربران"
CAT_SALES = "🛍 فروش و تست (مثل ربات مشتری)"
BACK = "🔙 بازگشت به منو اصلی"

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=CAT_CLIENTS), KeyboardButton(text=CAT_SECURITY)],
        [KeyboardButton(text=CAT_MAINTENANCE), KeyboardButton(text=CAT_PANEL)],
        [KeyboardButton(text=CAT_FINANCE), KeyboardButton(text=CAT_SALES)],
        [KeyboardButton(text="📖 راهنما")],
    ],
    resize_keyboard=True,
)

MENU_CLIENTS = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="👥 کلاینت‌ها"), KeyboardButton(text="🆕 کلاینت جدید")],
        [KeyboardButton(text="📦 ساخت انبوه"), KeyboardButton(text="🔍 وضعیت کلاینت")],
        [KeyboardButton(text="⏳ تمدید کلاینت"), KeyboardButton(text="➕ افزایش حجم/زمان")],
        [KeyboardButton(text="🔒 مسدود/فعال کلاینت"), KeyboardButton(text="🗑 حذف کلاینت")],
        [KeyboardButton(text="🔄 تمدید انبوه"), KeyboardButton(text="🗑 حذف انبوه (منقضی‌شده‌ها)")],
        [KeyboardButton(text="🛠 اصلاح Flow"), KeyboardButton(text="🔑 اصلاح کلیدها")],
        [KeyboardButton(text=BACK)],
    ],
    resize_keyboard=True,
)

MENU_SECURITY = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🚫 لیست مسدودی‌های Fail2ban")],
        [KeyboardButton(text="✅ رفع مسدودیت IP")],
        [KeyboardButton(text="🧱 وضعیت فایروال سرور ایران")],
        [KeyboardButton(text="🔬 تست محلی TLS اینباند WS")],
        [KeyboardButton(text=BACK)],
    ],
    resize_keyboard=True,
)

MENU_MAINTENANCE = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔎 بررسی کامل"), KeyboardButton(text="🔬 کانفیگ زنده Xray")],
        [KeyboardButton(text="🖥 وضعیت کامل سیستم"), KeyboardButton(text="💻 وضعیت سرور")],
        [KeyboardButton(text="📡 پینگ سرور ایران")],
        [KeyboardButton(text="📄 خطاهای اخیر"), KeyboardButton(text="🔎 بررسی یکپارچگی دیتابیس")],
        [KeyboardButton(text="💾 بکاپ دیتابیس"), KeyboardButton(text="🧪 تست تونل")],
        [KeyboardButton(text="♻️ ری‌استارت ربات فروش"), KeyboardButton(text="♻️ ری‌استارت ربات مدیریت (خودم)")],
        [KeyboardButton(text="♻️ ری‌استارت Xray"), KeyboardButton(text="♻️ ری‌استارت پنل X-UI (SSH)")],
        [KeyboardButton(text="⬆️ آپدیت کد"), KeyboardButton(text="🔑 تنظیم GitHub Token")],
        [KeyboardButton(text="🆔 شناسایی پردازش")],
        [KeyboardButton(text=BACK)],
    ],
    resize_keyboard=True,
)

MENU_PANEL = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🔧 اتصال پنل جدید"), KeyboardButton(text="🔑 تنظیم SSH سرور ایران")],
        [KeyboardButton(text="🌐 تغییر دامنه Reality"), KeyboardButton(text="🔌 فعال/غیرفعال اینباند")],
        [KeyboardButton(text="🔀 تغییر پورت اینباند"), KeyboardButton(text="☁️ تنظیم Cloudflare API")],
        [KeyboardButton(text="🚀 راه‌اندازی WS+TLS با Cloudflare")],
        [KeyboardButton(text=BACK)],
    ],
    resize_keyboard=True,
)

MENU_FINANCE = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📊 آمار کلی"), KeyboardButton(text="📊 گزارش مالی")],
        [KeyboardButton(text="🧾 سفارش‌های اخیر"), KeyboardButton(text="📢 پیام همگانی")],
        [KeyboardButton(text="💳 تنظیم شماره کارت")],
        [KeyboardButton(text="📤 سفارش‌های معطل"), KeyboardButton(text="⚙️ تنظیمات پرداخت خودکار")],
        [KeyboardButton(text=BACK)],
    ],
    resize_keyboard=True,
)

MENU_SALES = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📦 خرید عمده"), KeyboardButton(text="🛒 خرید سرویس")],
        [KeyboardButton(text="🔄 تمدید سرویس"), KeyboardButton(text="🧪 تست")],
        [KeyboardButton(text="📶 وضعیت سرویس من"), KeyboardButton(text="♻️ دریافت دوباره لینک")],
        [KeyboardButton(text="🆘 پشتیبانی")],
        [KeyboardButton(text=BACK)],
    ],
    resize_keyboard=True,
)

# Tapping a real devmenu button while mid-chat with a support customer
# should behave normally (leave the chat, run that button) instead of
# the tap getting swallowed and relayed to the customer as chat text.
_KNOWN_MENU_TEXTS = {
    btn.text
    for kb in (MENU, MENU_CLIENTS, MENU_SECURITY, MENU_MAINTENANCE, MENU_PANEL, MENU_FINANCE, MENU_SALES)
    for row in kb.keyboard
    for btn in row
}

HELP = (
    "🤖 ربات توسعه‌دهنده iranvpn — همه‌ی کارهای نگهداری و فروش از همین‌جا:\n\n"
    "یه دسته رو انتخاب کن تا دکمه‌های اون بخش باز بشه؛ هر وقت خواستی با 🔙 برگرد به منوی اصلی.\n"
    "نیازی به SSH یا پنل نیست، مگر برای امکانات مربوط به fail2ban/ری‌استارت پنل که یک‌بار باید "
    "SSH سرور ایران رو تنظیم کنی.\n"
    "برای لغو یک عملیات چندمرحله‌ای هر وقت خواستی /cancel بفرست."
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


@router.message(Command("cancel", "stop"))
async def cancel(message: Message):
    if not _admin(message):
        return
    had = _pending.pop(message.from_user.id, None)
    await message.answer("لغو شد." if had else "چیزی برای لغو نبود.", reply_markup=MENU)


# ---------------------------------------------------------------- category navigation

@router.message(F.text == CAT_CLIENTS)
async def cat_clients(message: Message):
    if not _admin(message):
        return
    await message.answer("👥 مدیریت کلاینت‌ها:", reply_markup=MENU_CLIENTS)


@router.message(F.text == CAT_SECURITY)
async def cat_security(message: Message):
    if not _admin(message):
        return
    await message.answer("🔒 امنیت — نیاز به 🔑 تنظیم SSH سرور ایران داره (تو ⚙️ تنظیمات پنل و SSH):",
                         reply_markup=MENU_SECURITY)


@router.message(F.text == CAT_MAINTENANCE)
async def cat_maintenance(message: Message):
    if not _admin(message):
        return
    await message.answer("🛠 نگهداری سرور:", reply_markup=MENU_MAINTENANCE)


@router.message(F.text == CAT_PANEL)
async def cat_panel(message: Message):
    if not _admin(message):
        return
    await message.answer("⚙️ تنظیمات پنل و SSH:", reply_markup=MENU_PANEL)


@router.message(F.text == CAT_FINANCE)
async def cat_finance(message: Message):
    if not _admin(message):
        return
    await message.answer("💰 مالی، آمار و کاربران:", reply_markup=MENU_FINANCE)


@router.message(F.text == CAT_SALES)
async def cat_sales(message: Message):
    if not _admin(message):
        return
    await message.answer("🛍 فروش و تست — همون کاری که ربات مشتری می‌کنه:", reply_markup=MENU_SALES)


@router.message(F.text == BACK)
async def back_to_menu(message: Message):
    if not _admin(message):
        return
    await message.answer("منوی اصلی:", reply_markup=MENU)


# ---------------------------------------------------------------- existing
# commands from ops.py, wrapped as buttons — same handlers, no duplicated
# logic, so a fix there is a fix here too.

@router.message(F.text == "🔎 بررسی کامل")
async def btn_diag(message: Message):
    await ops.diag(message)


@router.message(F.text == "🔬 کانفیگ زنده Xray")
async def btn_live_config(message: Message):
    await ops.live_config(message)


@router.message(F.text == "👥 کلاینت‌ها")
async def btn_clients(message: Message):
    await clientlist.show_list(message)


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


@router.message(F.text == "🔀 تغییر پورت اینباند")
async def ask_new_port(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "change_port"}
    await message.answer(
        "پورت جدید اینباند رو بفرست (عددی بین ۱ تا ۶۵۵۳۵، غیر از ۴۴۳ و پورت پنل).\n"
        "این کار برای دور زدن احتمالی محافظت Anti-DDoS/WAF ArvanCloud روی پورت ۴۴۳ "
        "کاربرد داره. بعدش یادت نره یه کلاینت جدید بسازی تا لینک با پورت جدید بگیری — "
        "و شاید لازم بشه پورت جدید رو تو فایروال/Anti-DDoS خود ArvanCloud هم باز کنی.\n\n"
        "/cancel برای لغو."
    )


async def _apply_new_port(message: Message, port_text: str):
    try:
        new_port = int(port_text.strip())
    except ValueError:
        await message.answer("عدد نامعتبر. دوباره از 🔀 تغییر پورت اینباند شروع کن.")
        return
    if not (1 <= new_port <= 65535):
        await message.answer("پورت باید بین ۱ تا ۶۵۵۳۵ باشه.")
        return

    x = XUIClient()
    try:
        inbound = x.get_inbound()
        stream = inbound.get("streamSettings")
        stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
        body = {
            "enable": inbound.get("enable", True),
            "remark": inbound.get("remark", ""),
            "listen": inbound.get("listen", ""),
            "port": new_port,
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
        msg = (f"✅ پورت اینباند به {new_port} تغییر کرد و Xray ری‌استارت شد.\n"
              "حالا یه کلاینت جدید بساز (🆕 کلاینت جدید) تا لینک با پورت جدید بگیری.")

        # A port that's open in Xray but not in the server's own firewall
        # fails silently (packets just get dropped) — this is exactly what
        # bit us moving to 8443 the first time. Auto-opening it here means
        # that specific mistake can't repeat.
        if iran_ssh.configured():
            try:
                out, _ = iran_ssh.run(f"sudo ufw allow {new_port}/tcp && echo UFW_OK")
                if "UFW_OK" in out:
                    msg += f"\n✅ پورت {new_port}/tcp تو فایروال (ufw) سرور ایران هم باز شد."
                else:
                    msg += f"\n⚠️ باز کردن پورت تو ufw نامشخص موند:\n{out}"
            except iran_ssh.IranSSHError as e:
                msg += f"\n⚠️ نتونستم فایروال ایران رو خودکار باز کنم ({e}) — با 🧱 وضعیت فایروال سرور ایران چک کن."
        else:
            msg += "\n⚠️ SSH سرور ایران تنظیم نیست — اگه پورت جدید تو فایروال بسته باشه، دستی باز کن."
        await message.answer(msg)
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ ناموفق: {e}")


# ---------------------------------------------------------------- new: Cloudflare API setup
# api.cloudflare.com is unreachable from wherever this code is written, so
# validation has to happen here, inside the bot's own already-running
# process (which has ordinary internet access) — exactly the same shape
# as the Iran-SSH setup above.

@router.message(F.text == "☁️ تنظیم Cloudflare API")
async def ask_cloudflare_token(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "cloudflare_token"}
    await message.answer(
        "توکن API کلودفلر رو بفرست (باید حداقل دسترسی Zone:DNS:Edit داشته باشه).\n"
        "/cancel برای لغو."
    )


async def _apply_cloudflare_token(message: Message, token: str):
    token = token.strip()
    await message.answer("⏳ در حال بررسی توکن…")
    try:
        r = requests.get(
            "https://api.cloudflare.com/client/v4/user/tokens/verify",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        body = r.json()
    except Exception as e:
        await message.answer(f"❌ اتصال به Cloudflare ناموفق: {type(e).__name__}: {e}")
        return
    if not body.get("success"):
        await message.answer(f"❌ توکن نامعتبره:\n{body.get('errors')}")
        return

    env_path = _env_path()
    _set_env_var(env_path, "CLOUDFLARE_API_TOKEN", token)
    await message.answer("✅ توکن تایید شد و ذخیره شد. ربات مدیریت ری‌استارت می‌شه…")
    _, dev = _service_names()
    subprocess.Popen(["systemctl", "restart", dev])


@router.message(F.text == "🔑 تنظیم GitHub Token")
async def ask_github_token(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "github_token"}
    await message.answer(
        "GitHub personal access token رو بفرست — چون ریپو پابلیکه به هیچ scope خاصی نیاز نیست، "
        "فقط سقف درخواست /update و setup رو از ۶۰ به ۵۰۰۰ در ساعت می‌بره بالا.\n"
        "/cancel برای لغو."
    )


async def _apply_github_token(message: Message, token: str):
    token = token.strip()
    await message.answer("⏳ در حال بررسی توکن…")
    try:
        r = requests.get(
            "https://api.github.com/rate_limit",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "irannewvpn-bot"},
            timeout=15,
        )
        body = r.json()
    except Exception as e:
        await message.answer(f"❌ اتصال به GitHub ناموفق: {type(e).__name__}: {e}")
        return
    limit = body.get("rate", {}).get("limit", 0)
    if r.status_code != 200 or limit <= 60:
        await message.answer(f"❌ توکن تایید نشد (سقف: {limit}):\n{body}")
        return

    env_path = _env_path()
    _set_env_var(env_path, "GITHUB_TOKEN", token)
    await message.answer(f"✅ توکن تایید شد (سقف الان {limit} درخواست/ساعت). ذخیره شد. ربات مدیریت ری‌استارت می‌شه…")
    _, dev = _service_names()
    subprocess.Popen(["systemctl", "restart", dev])


@router.message(F.text == "💳 تنظیم شماره کارت")
async def ask_card_number(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "card_setup", "stage": "number"}
    await message.answer(
        "شماره کارتی که مشتری‌ها باید بهش واریز کنن رو بفرست (فقط رقم، فاصله یا خط تیره اشکالی نداره):\n"
        "/cancel برای لغو."
    )


async def _card_setup_step(message: Message, pending: dict):
    stage = pending["stage"]
    text = message.text.strip()
    if stage == "number":
        pending["number"] = text
        pending["stage"] = "owner"
        _pending[message.from_user.id] = pending
        await message.answer("نام و فامیل صاحب کارت رو دقیقاً به لاتین بفرست (همونی که رو رسید نشون داده می‌شه):")
        return
    if stage == "owner":
        _pending.pop(message.from_user.id, None)
        await _apply_card(message, pending["number"], text)


async def _apply_card(message: Message, number: str, owner: str):
    env_path = _env_path()
    _set_env_var(env_path, "CARD_NUMBER", number)
    _set_env_var(env_path, "CARD_OWNER", owner)
    await message.answer(
        f"✅ ذخیره شد:\n💳 {number}\n👤 {owner}\n\nهر دو ربات ری‌استارت می‌شن…"
    )
    sales, dev = _service_names()
    subprocess.Popen(["systemctl", "restart", sales])
    subprocess.Popen(["systemctl", "restart", dev])


@router.message(F.text == "🚀 راه‌اندازی WS+TLS با Cloudflare")
async def ask_ws_subdomain(message: Message):
    if not _admin(message):
        return
    if not config.CLOUDFLARE_API_TOKEN:
        await message.answer("اول باید ☁️ تنظیم Cloudflare API رو انجام بدی.")
        return
    if not iran_ssh.configured():
        await message.answer("اول باید 🔑 تنظیم SSH سرور ایران رو انجام بدی (برای نوشتن گواهی روی سرور لازمه).")
        return
    _pending[message.from_user.id] = {"action": "ws_tls_setup"}
    await message.answer(
        "زیردامنه‌ی دلخواه (فقط حروف/عدد انگلیسی، بدون نقطه) رو بفرست — مثلاً اگه بخوای "
        "cdn1.behrad.win بشه فقط بفرست:\n\ncdn1\n\n"
        "این یه اینباند تازه‌ی VLESS+WebSocket+TLS پشت Cloudflare می‌سازه (کنار همون Reality "
        "قبلی، بدون حذفش) و یه کلاینت تست هم می‌سازه. /cancel برای لغو."
    )


async def _do_ws_tls_setup(message: Message, subdomain: str):
    subdomain = subdomain.strip().lower()
    if not subdomain or not subdomain.isalnum():
        await message.answer("زیردامنه نامعتبره — فقط حروف/عدد انگلیسی، بدون نقطه یا فاصله.")
        return

    from utils import cloudflare

    domain = "behrad.win"
    hostname = f"{subdomain}.{domain}"
    origin_ip = config.XUI_PUBLIC_HOST or "85.198.48.9"
    await message.answer(f"⏳ در حال راه‌اندازی {hostname}…")

    try:
        zone_id = cloudflare.get_zone_id(domain)
        cloudflare.create_or_update_dns_record(zone_id, hostname, origin_ip)
    except cloudflare.CloudflareError as e:
        await message.answer(f"❌ ساخت رکورد DNS ناموفق: {e}")
        return
    await message.answer(f"✅ DNS: {hostname} → سرور ایران (پشت Cloudflare، پروکسی‌شده)")

    # A separate try: needs a permission (Zone Settings) the token might not
    # have, and DNS/cert/inbound are all still worth doing even if this one
    # step needs to be set by hand in the dashboard instead.
    try:
        cloudflare.set_ssl_mode(zone_id, "full")
        await message.answer(
            "✅ حالت SSL/TLS رو ست کردم Full (نه Flexible) — وگرنه Cloudflare با HTTP ساده "
            "به سرور وصل می‌شد و Xray (که فقط TLS می‌فهمه) جوابی نمی‌داد."
        )
    except cloudflare.CloudflareError as e:
        await message.answer(
            f"⚠️ نتونستم حالت SSL/TLS رو خودکار عوض کنم ({e}) — دستی تو Cloudflare چک کن: "
            f"دامنه‌ی {domain} → SSL/TLS → Overview → باید رو Full یا Full (strict) باشه، نه Flexible."
        )

    try:
        key_pem, csr_pem = cloudflare.generate_key_and_csr(hostname)
        cert_result = cloudflare.request_origin_certificate([hostname], csr_pem)
        cert_pem = cert_result["certificate"]
    except cloudflare.CloudflareError as e:
        await message.answer(f"❌ صدور گواهی TLS ناموفق: {e}")
        return
    await message.answer("✅ گواهی TLS از Cloudflare صادر شد.")

    cert_path = f"/root/cert-{subdomain}.crt"
    key_path = f"/root/cert-{subdomain}.key"
    try:
        iran_ssh.write_file(cert_path, cert_pem)
        iran_ssh.write_file(key_path, key_pem)
    except iran_ssh.IranSSHError as e:
        await message.answer(f"❌ نوشتن گواهی روی سرور ایران ناموفق: {e}")
        return
    await message.answer("✅ گواهی روی سرور ایران نوشته شد.")

    remark = f"ws-tls-{subdomain}"
    ws_path = "/" + os.urandom(6).hex()
    body = {
        "enable": True,
        "remark": remark,
        "listen": "",
        "port": 2053,  # one of Cloudflare's allowed proxied HTTPS ports
        "protocol": "vless",
        "expiryTime": 0,
        "total": 0,
        "settings": {"clients": [], "decryption": "none"},
        "streamSettings": {
            "network": "ws",
            "security": "tls",
            # Cloudflare routes proxied requests by the HTTP Host header —
            # an empty one means the WebSocket upgrade never reaches this
            # origin at all, which looked exactly like "connected, zero
            # bytes" from the client's side.
            "wsSettings": {"path": ws_path, "headers": {"Host": hostname}},
            "tlsSettings": {
                "serverName": hostname,
                "certificates": [{"certificateFile": cert_path, "keyFile": key_path}],
            },
        },
        "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
    }
    x = XUIClient()
    try:
        # Re-running this for the same subdomain should fix the existing
        # inbound in place, not pile up duplicates.
        existing_id = None
        for ib in x._request("GET", "/panel/api/inbounds/list") or []:
            if ib.get("remark") == remark:
                existing_id = ib.get("id")
                break
        if existing_id:
            x._request("POST", f"/panel/api/inbounds/update/{existing_id}", json=body)
            new_id = existing_id
        else:
            new_inbound = x._request("POST", "/panel/api/inbounds/add", json=body)
            new_id = new_inbound["id"]
    except (XUIError, KeyError, TypeError) as e:
        await message.answer(f"❌ ساخت/اصلاح اینباند ناموفق: {e}")
        return
    fw_msg = f"✅ اینباند آماده شد (id={new_id}, پورت 2053, مسیر {ws_path})."
    # Same bug that bit the Reality port change: Xray can be listening fine,
    # but if ufw never got a rule for this port, Cloudflare's edge reaches
    # the origin IP and gets silently dropped — the local 127.0.0.1 TLS
    # test bypasses ufw entirely (loopback), so it looks fine while the
    # real public path is dead. That's exactly "Connected, 0 bytes".
    if iran_ssh.configured():
        try:
            out, _ = iran_ssh.run("sudo ufw allow 2053/tcp && echo UFW_OK")
            if "UFW_OK" in out:
                fw_msg += "\n✅ پورت 2053/tcp تو فایروال (ufw) سرور ایران هم باز شد."
            else:
                fw_msg += f"\n⚠️ باز کردن پورت تو ufw نامشخص موند:\n{out}"
        except iran_ssh.IranSSHError as e:
            fw_msg += f"\n⚠️ نتونستم فایروال ایران رو خودکار باز کنم ({e}) — با 🧱 وضعیت فایروال سرور ایران چک کن."
    else:
        fw_msg += "\n⚠️ SSH سرور ایران تنظیم نیست — اگه پورت 2053 تو فایروال بسته باشه، دستی باز کن."
    await message.answer(fw_msg)

    # Unique every run — re-running this for the same subdomain (e.g. to
    # pick up a config fix) would otherwise collide with the previous
    # run's still-existing test client and fail outright.
    test_email = f"wstest-{subdomain}-{int(time.time())}"
    try:
        x._request("POST", "/panel/api/server/restartXrayService")
        client = x.add_client(email=test_email, days=1, inbound_id=new_id)
        # inbound_id=new_id, not the configured default: build_vless_link
        # now swaps the address for the WS Host header on its own for
        # whichever inbound it's told to look at, so this only needs to
        # point it at the inbound this flow just created.
        link = x.build_vless_link(client["uuid"], test_email, inbound_id=new_id)
    except XUIError as e:
        await message.answer(f"⚠️ اینباند ساخته شد ولی ساخت کلاینت تست ناموفق بود: {e}")
        return

    await message.answer(
        f"🎉 آماده‌ست! لینک تست:\n\n<code>{link}</code>\n\n"
        "این رو تو اپ گوشیت وارد کن و امتحان کن. اینباند Reality قبلی هم دست‌نخورده باقی موند "
        "(id همون که قبلاً بود).",
        parse_mode="HTML",
    )


# ---------------------------------------------------------------- new: repoint at a different panel

@router.message(F.text == "🔧 اتصال پنل جدید")
async def ask_new_panel(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "new_panel", "stage": "url"}
    await message.answer(
        "آدرس کامل پنل رو بفرست (شامل پورت و web base path)، مثلاً:\n"
        "http://85.198.48.9:60231/xxxxxxxx\n\n/cancel برای لغو."
    )


async def _new_panel_step(message: Message, pending: dict):
    stage = pending["stage"]
    text = message.text.strip()

    if stage == "url":
        pending["url"] = text.rstrip("/")
        pending["stage"] = "user"
        _pending[message.from_user.id] = pending
        await message.answer("یوزرنیم پنل رو بفرست:")
        return
    if stage == "user":
        pending["user"] = text
        pending["stage"] = "password"
        _pending[message.from_user.id] = pending
        await message.answer("پسورد پنل رو بفرست:")
        return
    if stage == "password":
        pending["password"] = text
        pending["stage"] = "token"
        _pending[message.from_user.id] = pending
        await message.answer("اگه API token داری بفرست، وگرنه فقط - بفرست:")
        return
    if stage == "token":
        pending["token"] = "" if text == "-" else text
        pending["stage"] = "inbound"
        _pending[message.from_user.id] = pending
        await message.answer("شماره‌ی inbound ID رو بفرست (اگه نمی‌دونی 1 بفرست):")
        return
    if stage == "inbound":
        try:
            inbound_id = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر. از 🔧 اتصال پنل جدید دوباره شروع کن.")
            return
        _pending.pop(message.from_user.id, None)
        await _apply_new_panel(message, pending["url"], pending["user"], pending["password"],
                                pending["token"], inbound_id)


async def _apply_new_panel(message: Message, url: str, user: str, password: str, token: str, inbound_id: int):
    await message.answer("⏳ در حال بررسی اتصال به پنل جدید…")
    test = XUIClient(base_url=url, username=user, password=password, api_token=token)
    try:
        test.get_inbound(inbound_id)
    except XUIError as e:
        await message.answer(f"❌ اتصال ناموفق — چیزی تغییر نکرد:\n{e}")
        return

    env_path = _env_path()
    _set_env_var(env_path, "XUI_BASE_URL", url)
    _set_env_var(env_path, "XUI_USERNAME", user)
    _set_env_var(env_path, "XUI_PASSWORD", password)
    _set_env_var(env_path, "XUI_API_TOKEN", token)
    _set_env_var(env_path, "XUI_INBOUND_ID", str(inbound_id))
    await message.answer("✅ اتصال تایید شد. تنظیمات ذخیره شد و هر دو ربات ری‌استارت می‌شن…")
    sales, dev = _service_names()
    subprocess.Popen(["systemctl", "restart", sales])
    subprocess.Popen(["systemctl", "restart", dev])


# ---------------------------------------------------------------- new: Iran server SSH setup

@router.message(F.text == "🔑 تنظیم SSH سرور ایران")
async def ask_iran_ssh(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "iran_ssh", "stage": "host"}
    await message.answer("آی‌پی یا هاست سرور ایران رو بفرست (مثلاً 85.198.48.9). /cancel برای لغو.")


async def _iran_ssh_step(message: Message, pending: dict):
    stage = pending["stage"]
    text = message.text.strip()
    if stage == "host":
        pending["host"] = text
        pending["stage"] = "port"
        _pending[message.from_user.id] = pending
        await message.answer("پورت SSH رو بفرست (اگه نمی‌دونی 22 بفرست):")
        return
    if stage == "port":
        try:
            pending["port"] = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر. از اول شروع کن.")
            return
        pending["stage"] = "user"
        _pending[message.from_user.id] = pending
        await message.answer("یوزرنیم SSH رو بفرست (مثلاً root یا ubuntu):")
        return
    if stage == "user":
        pending["user"] = text
        pending["stage"] = "password"
        _pending[message.from_user.id] = pending
        await message.answer("پسورد SSH رو بفرست:")
        return
    if stage == "password":
        _pending.pop(message.from_user.id, None)
        await _apply_iran_ssh(message, pending["host"], pending["port"], pending["user"], text)


async def _apply_iran_ssh(message: Message, host: str, port: int, user: str, password: str):
    await message.answer("⏳ در حال تست اتصال SSH…")
    try:
        import paramiko
    except ImportError:
        await message.answer("❌ ماژول paramiko نصب نیست؛ یک بار /update بزن.")
        return

    # A plain SSHClient.connect() failure can't tell "wrong password" apart
    # from "this server doesn't allow password auth for this user at all"
    # (very common default on Ubuntu cloud images: PermitRootLogin
    # prohibit-password — key-only, any password gets the same generic
    # rejection). Talking to Transport directly surfaces which auth types
    # the server actually offers, which settles that question outright.
    transport = None
    try:
        transport = paramiko.Transport((host, port))
        transport.connect()
        try:
            transport.auth_password(username=user, password=password)
        except paramiko.ssh_exception.BadAuthenticationType as e:
            allowed = ", ".join(e.allowed_types) or "(هیچ‌کدام)"
            await message.answer(
                "❌ این سرور اصلاً ورود با رمز عبور رو برای این یوزر قبول نمی‌کنه "
                f"(معمولاً تنظیمات پیش‌فرض Ubuntu Cloud) — روش‌های مجاز: {allowed}\n\n"
                "یعنی رمز اشتباه نیست؛ رمز عبور اصلاً به‌عنوان روش ورود فعال نیست. "
                "باید یا از کنسول وب یه کلید SSH اضافه کنی، یا تو sshd_config یوزر "
                "و رمز رو دستی فعال کنی. چیزی ذخیره نشد."
            )
            return
        except paramiko.ssh_exception.AuthenticationException:
            await message.answer(
                "❌ سرور ورود با رمز عبور رو قبول می‌کنه، ولی این یوزر/رمز مشخص رد شد "
                "(یعنی رمز واقعاً اشتباهه، نه محدودیت سرور). چیزی ذخیره نشد."
            )
            return
        transport.open_session().close()
    except Exception as e:
        await message.answer(f"❌ اتصال ناموفق — چیزی ذخیره نشد:\n{type(e).__name__}: {e}")
        return
    finally:
        if transport is not None:
            transport.close()

    env_path = _env_path()
    _set_env_var(env_path, "IRAN_SSH_HOST", host)
    _set_env_var(env_path, "IRAN_SSH_PORT", str(port))
    _set_env_var(env_path, "IRAN_SSH_USER", user)
    _set_env_var(env_path, "IRAN_SSH_PASSWORD", password)
    await message.answer("✅ اتصال تایید شد و ذخیره شد. ربات مدیریت ری‌استارت می‌شه…")
    _, dev = _service_names()
    subprocess.Popen(["systemctl", "restart", dev])


# ---------------------------------------------------------------- new: fail2ban (needs Iran SSH)

def _jail_list(status_out: str) -> list[str]:
    for line in status_out.splitlines():
        if "Jail list" in line:
            after = line.split(":", 1)[-1]
            return [j.strip() for j in after.replace("\t", ",").split(",") if j.strip()]
    return []


@router.message(F.text == "🚫 لیست مسدودی‌های Fail2ban")
async def fail2ban_list(message: Message):
    if not _admin(message):
        return
    try:
        out, _ = iran_ssh.run("sudo fail2ban-client status")
    except iran_ssh.IranSSHError as e:
        await message.answer(f"❌ {e}")
        return
    jails = _jail_list(out)
    if not jails:
        await message.answer("هیچ jail‌ای پیدا نشد یا fail2ban نصب نیست.")
        return

    lines = []
    for jail in jails:
        try:
            jout, _ = iran_ssh.run(f"sudo fail2ban-client status {jail}")
        except iran_ssh.IranSSHError as e:
            lines.append(f"• {jail}: خطا ({e})")
            continue
        banned = ""
        for line in jout.splitlines():
            if "Banned IP list" in line:
                banned = line.split(":", 1)[-1].strip()
        lines.append(f"• {jail}: {banned or '(خالی)'}")
    await message.answer("🚫 مسدودی‌های فعلی:\n\n" + "\n".join(lines))


@router.message(F.text == "🧱 وضعیت فایروال سرور ایران")
async def iran_firewall_status(message: Message):
    """OS-level firewall on the Iran server itself — ufw/iptables, checked
    directly over SSH. This is the one thing the X-UI panel's API can never
    see: a port can be perfectly configured in Xray and still be silently
    dropped by the server's own firewall before ever reaching it."""
    if not _admin(message):
        return
    try:
        x = XUIClient()
        port = x.get_inbound().get("port", 443)
    except (XUIError, ValueError):
        port = 443
    try:
        out, _ = iran_ssh.run(
            "echo '--- ufw status ---'; sudo ufw status verbose 2>&1; "
            "echo '--- iptables (INPUT chain) ---'; sudo iptables -L INPUT -n --line-numbers 2>&1; "
            f"echo '--- listening on port {port}? ---'; sudo ss -ltnp 2>&1 | grep -E \":{port}\\b\" || echo '(چیزی روی این پورت گوش نمی‌ده!)'; "
            "echo '--- listening on port 443? ---'; sudo ss -ltnp 2>&1 | grep -E ':443\\b' || echo '(چیزی روی 443 گوش نمی‌ده)'"
        )
    except iran_ssh.IranSSHError as e:
        await message.answer(f"❌ {e}")
        return
    await message.answer(f"🧱 فایروال و پورت‌های در حال گوش‌دادن (سرور ایران):\n\n<pre>{out[-3500:]}</pre>",
                         parse_mode="HTML")


@router.message(F.text == "🔬 تست محلی TLS اینباند WS")
async def ws_tls_local_test(message: Message):
    """A local TLS handshake against the WS+TLS inbound, from the Iran
    server itself — this is the one test that removes Cloudflare from the
    picture entirely. If this fails too, the problem is Xray/the cert, not
    the CDN; if this succeeds, the problem is specifically between
    Cloudflare and the origin (or Cloudflare and the client)."""
    if not _admin(message):
        return
    try:
        out, _ = iran_ssh.run(
            "echo '--- listening on 2053? ---'; sudo ss -ltnp 2>&1 | grep -E ':2053\\b' "
            "|| echo '(چیزی روی 2053 گوش نمی‌ده!)'; "
            "echo '--- local TLS handshake (bypasses Cloudflare) ---'; "
            "echo | timeout 8 openssl s_client -connect 127.0.0.1:2053 -servername cdn1.behrad.win 2>&1 "
            "| head -25; "
            "echo '--- recent xray/x-ui errors mentioning tls/cert ---'; "
            "sudo journalctl -u x-ui -n 200 --no-pager 2>&1 | grep -iE 'tls|cert|2053' | tail -20"
        )
    except iran_ssh.IranSSHError as e:
        await message.answer(f"❌ {e}")
        return
    await message.answer(f"🔬 تست محلی TLS (بدون Cloudflare):\n\n<pre>{out[-3500:]}</pre>", parse_mode="HTML")


@router.message(F.text == "✅ رفع مسدودیت IP")
async def ask_unban(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "unban_ip"}
    await message.answer("آی‌پی‌ای که باید رفع مسدودیت بشه رو بفرست (روی همه‌ی jail‌ها امتحان می‌شه). /cancel برای لغو.")


async def _do_unban(message: Message, ip: str):
    try:
        out, _ = iran_ssh.run("sudo fail2ban-client status")
    except iran_ssh.IranSSHError as e:
        await message.answer(f"❌ {e}")
        return
    jails = _jail_list(out)
    freed = []
    for jail in jails:
        try:
            o, _ = iran_ssh.run(f"sudo fail2ban-client set {jail} unbanip {ip}")
            if o.strip():
                freed.append(jail)
        except iran_ssh.IranSSHError:
            pass
    if freed:
        await message.answer(f"✅ آی‌پی {ip} از این jail‌ها آزاد شد: {', '.join(freed)}")
    else:
        await message.answer(f"آی‌پی {ip} در هیچ jail‌ای مسدود نبود (یا خطا رخ داد).")


# ---------------------------------------------------------------- new: ping + full status + errors

@router.message(F.text == "📡 پینگ سرور ایران")
async def ping_iran(message: Message):
    if not _admin(message):
        return
    host = config.XUI_PUBLIC_HOST or config.IRAN_SSH_HOST
    if not host:
        await message.answer("آدرس سرور ایران مشخص نیست (XUI_PUBLIC_HOST خالیه).")
        return
    try:
        result = subprocess.run(["ping", "-c", "4", "-W", "3", host],
                                capture_output=True, text=True, timeout=20)
        await message.answer(f"📡 پینگ {host}:\n\n<pre>{result.stdout[-2500:]}</pre>", parse_mode="HTML")
    except Exception as e:
        await message.answer(f"❌ ping ناموفق: {type(e).__name__}: {e}")


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
    await message.answer("💻 وضعیت سرور (Nautilus):\n\n" + "\n".join(lines))


@router.message(F.text == "🖥 وضعیت کامل سیستم")
async def full_system_status(message: Message):
    if not _admin(message):
        return
    await ops.diag(message)
    await server_status(message)
    if iran_ssh.configured():
        try:
            out, _ = iran_ssh.run(
                "uptime && echo --- && free -h && echo --- && df -h / && echo --- && "
                "(sudo fail2ban-client status 2>/dev/null | grep 'Jail list' || echo 'fail2ban: n/a')"
            )
            await message.answer("🇮🇷 وضعیت سرور ایران:\n\n<pre>" + out[-3000:] + "</pre>", parse_mode="HTML")
        except iran_ssh.IranSSHError as e:
            await message.answer(f"🇮🇷 وضعیت سرور ایران: خطا ({e})")
    else:
        await message.answer("🇮🇷 برای وضعیت سرور ایران، اول 🔑 تنظیم SSH سرور ایران رو انجام بده.")


@router.message(F.text == "📄 خطاهای اخیر")
async def recent_errors(message: Message):
    if not _admin(message):
        return
    sales, dev = _service_names()
    for svc in (sales, dev):
        try:
            out = subprocess.run(["journalctl", "-u", svc, "-n", "25", "--no-pager", "-p", "err"],
                                 capture_output=True, text=True, timeout=15).stdout
        except Exception as e:
            out = f"({e})"
        await message.answer(f"📄 خطاهای اخیر {svc}:\n\n<pre>{(out or '(چیزی نبود)')[-2500:]}</pre>",
                             parse_mode="HTML")
    if iran_ssh.configured():
        try:
            out, _ = iran_ssh.run("sudo journalctl -u x-ui -n 25 --no-pager -p err 2>&1 || true")
            await message.answer(f"📄 خطاهای اخیر x-ui (ایران):\n\n<pre>{(out or '(چیزی نبود)')[-2500:]}</pre>",
                                 parse_mode="HTML")
        except iran_ssh.IranSSHError as e:
            await message.answer(f"📄 خطاهای x-ui (ایران): خطا در اتصال ({e})")


# ---------------------------------------------------------------- new: maintenance restarts + integrity

@router.message(F.text == "🔎 بررسی یکپارچگی دیتابیس")
async def db_integrity(message: Message):
    if not _admin(message):
        return
    try:
        with sqlite3.connect(config.DB_PATH) as conn:
            result = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        await message.answer(f"🔎 نتیجه‌ی بررسی دیتابیس: {result}")
    except Exception as e:
        await message.answer(f"❌ خطا: {type(e).__name__}: {e}")


@router.message(F.text == "♻️ ری‌استارت ربات فروش")
async def restart_sales(message: Message):
    if not _admin(message):
        return
    sales, _ = _service_names()
    await message.answer(f"♻️ در حال ری‌استارت {sales}…")
    subprocess.Popen(["systemctl", "restart", sales])


@router.message(F.text == "♻️ ری‌استارت ربات مدیریت (خودم)")
async def restart_self(message: Message):
    if not _admin(message):
        return
    _, dev = _service_names()
    await message.answer(f"♻️ در حال ری‌استارت {dev}…")
    subprocess.Popen(["systemctl", "restart", dev])


@router.message(F.text == "♻️ ری‌استارت پنل X-UI (SSH)")
async def restart_xui_panel(message: Message):
    if not _admin(message):
        return
    try:
        out, err = iran_ssh.run("sudo systemctl restart x-ui && echo RESTARTED")
    except iran_ssh.IranSSHError as e:
        await message.answer(f"❌ {e}")
        return
    if "RESTARTED" in out:
        await message.answer("✅ پنل X-UI روی سرور ایران ری‌استارت شد.")
    else:
        await message.answer(f"⚠️ نتیجه نامشخص:\n{out}\n{err}")


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


# ---------------------------------------------------------------- new: stats + orders + finance

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
        f"سفارش‌های تاییدشده: {s['orders_approved']} — جمع {s['revenue_total']:,} {config.CURRENCY_LABEL}\n"
        f"سفارش‌های در انتظار بررسی: {s['orders_pending']}"
    )


@router.message(F.text == "📊 گزارش مالی")
async def financial_report(message: Message):
    if not _admin(message):
        return
    periods = [("۲۴ ساعت گذشته", 24 * 3600), ("۷ روز گذشته", 7 * 24 * 3600),
              ("۳۰ روز گذشته", 30 * 24 * 3600), ("کل دوران", None)]
    lines = []
    for label, seconds in periods:
        cnt, total = db.report_since(seconds)
        lines.append(f"{label}: {cnt} سفارش — {total:,} {config.CURRENCY_LABEL}")
    await message.answer("📊 گزارش مالی:\n\n" + "\n".join(lines))


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
        lines.append(f"#{o['id']} — {o['plan_key']} — {o['amount']:,} {config.CURRENCY_LABEL} — {o['status']} — tg:{o['tg_id']}")
    await message.answer("🧾 ۱۰ سفارش اخیر:\n\n" + "\n".join(lines))


@router.message(F.text == "📤 سفارش‌های معطل")
async def pending_orders_cmd(message: Message):
    """Emergency manual path that stays available even with auto-approve
    on — every order still awaiting a review, each with the same
    approve/reject buttons the receipt-photo notification sends, so
    nothing is stuck waiting if the automatic (bank-SMS) route misses it."""
    if not _admin(message):
        return
    orders = db.pending_orders(20)
    if not orders:
        await message.answer("هیچ سفارش معطلی نیست ✅ همه‌چیز تسویه‌ست.")
        return
    await message.answer(f"{len(orders)} سفارش معطل:")
    now = int(time.time())
    for o in orders:
        mins = (now - o["created_at"]) // 60
        kind = f"تمدید «{o['renew_target_email']}»" if o["renew_target_email"] else o["plan_key"]
        await message.answer(
            f"سفارش #{o['id']} — tg:{o['tg_id']}\n"
            f"{kind} — {o['amount']:,} {config.CURRENCY_LABEL}\n"
            f"{mins} دقیقه پیش ثبت شده",
            reply_markup=admin_review_keyboard(o["id"]),
        )


@router.message(F.text == "⚙️ تنظیمات پرداخت خودکار")
async def auto_approve_settings(message: Message):
    if not _admin(message):
        return
    await message.answer(_auto_approve_text(), reply_markup=_auto_approve_keyboard())


def _auto_approve_text() -> str:
    state = "خودکار" if db.auto_approve_enabled() else "دستی"
    return (
        f"حالت فعلی تأیید پرداخت: {state}\n\n"
        "خودکار: واریز شناسایی‌شده (از طریق پیامک بانک) بلافاصله خودش تأیید و فعال می‌شه.\n"
        "دستی: فقط بهت خبر می‌ده، تأیید نهایی با خودته."
    )


def _auto_approve_keyboard():
    on = db.auto_approve_enabled()
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("✅ " if on else "") + "خودکار", callback_data="autoset:1"),
        InlineKeyboardButton(text=("✅ " if not on else "") + "دستی", callback_data="autoset:0"),
    ]])


@router.callback_query(F.data.startswith("autoset:"))
async def auto_approve_set(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return
    db.set_setting("auto_approve", callback.data.split(":", 1)[1])
    await callback.message.edit_text(_auto_approve_text(), reply_markup=_auto_approve_keyboard())
    await callback.answer()


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


# ---------------------------------------------------------------- new: single client create/lookup/increase
# GB/days are picked with inline buttons (a "سرویس با دکمه" flow) instead of
# always typing a number — the "✏️ مقدار دلخواه" button falls back to the
# original free-text stage for anything not on the quick list.

_GB_CHOICES = [10, 20, 30, 50, 100, 0]
_DAYS_CHOICES = [7, 30, 60, 90, 180, 365, 0]


def _chunk_buttons(buttons: list[InlineKeyboardButton], size: int) -> list[list[InlineKeyboardButton]]:
    return [buttons[i:i + size] for i in range(0, len(buttons), size)]


def _gb_options_keyboard(cb_prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=("نامحدود ♾" if v == 0 else f"{v} گیگ"), callback_data=f"{cb_prefix}:gb:{v}")
        for v in _GB_CHOICES
    ]
    rows = _chunk_buttons(buttons, 3)
    rows.append([InlineKeyboardButton(text="✏️ مقدار دلخواه", callback_data=f"{cb_prefix}:gb:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _days_options_keyboard(cb_prefix: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=("بدون انقضا ♾" if v == 0 else f"{v} روز"), callback_data=f"{cb_prefix}:days:{v}")
        for v in _DAYS_CHOICES
    ]
    rows = _chunk_buttons(buttons, 3)
    rows.append([InlineKeyboardButton(text="✏️ مقدار دلخواه", callback_data=f"{cb_prefix}:days:custom")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(F.text == "🆕 کلاینت جدید")
async def ask_new_client(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "new_client", "stage": "email"}
    await message.answer("ایمیل/شناسه‌ی کلاینت جدید رو بفرست (مثلاً user-ali). /cancel برای لغو.")


async def _new_client_step(message: Message, pending: dict):
    stage = pending["stage"]
    text = message.text.strip()
    if stage == "email":
        pending["email"] = text
        pending["stage"] = "gb"
        _pending[message.from_user.id] = pending
        await message.answer("چند گیگ؟ یکی از دکمه‌ها رو بزن، یا عدد دلخواه رو همینجا تایپ کن:",
                              reply_markup=_gb_options_keyboard("devnc"))
        return
    if stage == "gb":
        try:
            pending["gb"] = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        pending["stage"] = "days"
        _pending[message.from_user.id] = pending
        await message.answer("چند روز؟ یکی از دکمه‌ها رو بزن، یا عدد دلخواه رو همینجا تایپ کن:",
                              reply_markup=_days_options_keyboard("devnc"))
        return
    if stage == "days":
        try:
            days = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        _pending.pop(message.from_user.id, None)
        await _create_client(message, pending["email"], pending["gb"], days)


@router.callback_query(F.data.startswith("devnc:gb:"))
async def new_client_gb_button(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending or pending.get("action") != "new_client" or pending.get("stage") != "gb":
        await callback.answer("این مرحله دیگه معتبر نیست — از 🆕 کلاینت جدید دوباره شروع کن.", show_alert=True)
        return
    value = callback.data.split(":", 2)[2]
    if value == "custom":
        await callback.answer()
        await callback.message.answer("عدد گیگ دلخواه رو تایپ کن:")
        return
    pending["gb"] = int(value)
    pending["stage"] = "days"
    _pending[callback.from_user.id] = pending
    gb_label = "نامحدود ♾" if pending["gb"] == 0 else f"{pending['gb']} گیگ"
    await callback.answer(f"حجم: {gb_label}")
    await callback.message.edit_text(f"✅ حجم: {gb_label}\n\nحالا چند روز؟",
                                      reply_markup=_days_options_keyboard("devnc"))


@router.callback_query(F.data.startswith("devnc:days:"))
async def new_client_days_button(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending or pending.get("action") != "new_client" or pending.get("stage") != "days":
        await callback.answer("این مرحله دیگه معتبر نیست — از 🆕 کلاینت جدید دوباره شروع کن.", show_alert=True)
        return
    value = callback.data.split(":", 2)[2]
    if value == "custom":
        await callback.answer()
        await callback.message.answer("تعداد روز دلخواه رو تایپ کن:")
        return
    days = int(value)
    _pending.pop(callback.from_user.id, None)
    await callback.answer()
    await callback.message.edit_text(f"⏳ در حال ساخت کلاینت {pending['email']}…")
    await _create_client(callback.message, pending["email"], pending["gb"], days)


async def _create_client(message: Message, email: str, gb: int, days: int):
    x = XUIClient()
    try:
        client = x.add_client(email=email, gb=gb, days=days)
        link = x.build_vless_link(client["uuid"], email)
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")
        return
    await message.answer(f"✅ کلاینت ساخته شد: {email}\n\n<code>{link}</code>", parse_mode="HTML")


@router.message(F.text == "📦 ساخت انبوه")
async def ask_bulk_create(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "bulk_create", "stage": "count"}
    await message.answer("چند تا کلاینت ساخته بشه؟ (حداکثر ۲۰۰) عدد بفرست. /cancel برای لغو.")


async def _bulk_create_step(message: Message, pending: dict):
    stage = pending["stage"]
    text = message.text.strip()
    if stage == "count":
        try:
            count = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        if count < 1 or count > 200:
            await message.answer("عدد باید بین ۱ تا ۲۰۰ باشه.")
            return
        pending["count"] = count
        pending["stage"] = "gb"
        _pending[message.from_user.id] = pending
        await message.answer("هر کلاینت چند گیگ؟ یکی از دکمه‌ها رو بزن، یا عدد دلخواه رو تایپ کن:",
                              reply_markup=_gb_options_keyboard("devbulk"))
        return
    if stage == "gb":
        try:
            pending["gb"] = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        pending["stage"] = "days"
        _pending[message.from_user.id] = pending
        await message.answer("هر کلاینت چند روز؟ یکی از دکمه‌ها رو بزن، یا عدد دلخواه رو تایپ کن:",
                              reply_markup=_days_options_keyboard("devbulk"))
        return
    if stage == "days":
        try:
            days = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        _pending.pop(message.from_user.id, None)
        await _do_bulk_create(message, pending["count"], pending["gb"], days)


@router.callback_query(F.data.startswith("devbulk:gb:"))
async def bulk_create_gb_button(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending or pending.get("action") != "bulk_create" or pending.get("stage") != "gb":
        await callback.answer("این مرحله دیگه معتبر نیست — از 📦 ساخت انبوه دوباره شروع کن.", show_alert=True)
        return
    value = callback.data.split(":", 2)[2]
    if value == "custom":
        await callback.answer()
        await callback.message.answer("عدد گیگ دلخواه رو تایپ کن:")
        return
    pending["gb"] = int(value)
    pending["stage"] = "days"
    _pending[callback.from_user.id] = pending
    gb_label = "نامحدود ♾" if pending["gb"] == 0 else f"{pending['gb']} گیگ"
    await callback.answer(f"حجم: {gb_label}")
    await callback.message.edit_text(f"✅ حجم هر کلاینت: {gb_label}\n\nحالا چند روز؟",
                                      reply_markup=_days_options_keyboard("devbulk"))


@router.callback_query(F.data.startswith("devbulk:days:"))
async def bulk_create_days_button(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return
    pending = _pending.get(callback.from_user.id)
    if not pending or pending.get("action") != "bulk_create" or pending.get("stage") != "days":
        await callback.answer("این مرحله دیگه معتبر نیست — از 📦 ساخت انبوه دوباره شروع کن.", show_alert=True)
        return
    value = callback.data.split(":", 2)[2]
    if value == "custom":
        await callback.answer()
        await callback.message.answer("تعداد روز دلخواه رو تایپ کن:")
        return
    days = int(value)
    _pending.pop(callback.from_user.id, None)
    await callback.answer()
    await callback.message.edit_text(f"⏳ در حال ساخت {pending['count']} کلاینت…")
    await _do_bulk_create(callback.message, pending["count"], pending["gb"], days)


async def _do_bulk_create(message: Message, count: int, gb: int, days: int):
    x = XUIClient()
    prefix = f"batch{int(time.time())}"
    created, failed = [], []
    for i in range(count):
        email = f"{prefix}-{i + 1}"
        try:
            client = x.add_client(email=email, gb=gb, days=days)
            link = x.build_vless_link(client["uuid"], email)
            created.append((email, link))
        except XUIError as e:
            failed.append(f"{email}: {e}")
    text = f"✅ {len(created)} کلاینت ساخته شد (پیشوند: {prefix}).\n\n"
    text += "\n\n".join(f"{em}\n{link}" for em, link in created[:10])
    if len(created) > 10:
        text += f"\n\n…و {len(created) - 10} مورد دیگه."
    if failed:
        text += "\n\n❌ ناموفق:\n" + "\n".join(failed[:5])
    await message.answer(text)


# "کلاینت‌ها" and "وضعیت کلاینت" both just want the same client-status
# picker (list, pick one, see its status) — handlers/clientlist.py owns the
# actual implementation (shared with the sales bot's /clients) so there is
# only one place to fix a bug in it.

@router.message(F.text == "🔍 وضعیت کلاینت")
async def ask_client_status(message: Message):
    await clientlist.show_list(message)


@router.message(F.text == "➕ افزایش حجم/زمان")
async def ask_increase(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "increase", "stage": "email"}
    await message.answer("ایمیل کلاینت رو بفرست. /cancel برای لغو.")


async def _increase_step(message: Message, pending: dict):
    stage = pending["stage"]
    text = message.text.strip()
    if stage == "email":
        pending["email"] = text
        pending["stage"] = "gb"
        _pending[message.from_user.id] = pending
        await message.answer("چند گیگ اضافه بشه؟ (0 = بدون تغییر — روی پلن‌های نامحدود بی‌اثره)")
        return
    if stage == "gb":
        try:
            pending["add_gb"] = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        pending["stage"] = "days"
        _pending[message.from_user.id] = pending
        await message.answer("چند روز اضافه بشه؟ (0 = بدون تغییر)")
        return
    if stage == "days":
        try:
            add_days = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        _pending.pop(message.from_user.id, None)
        await _do_increase(message, pending["email"], pending["add_gb"], add_days)


async def _do_increase(message: Message, email: str, add_gb: int, add_days: int):
    x = XUIClient()
    t = x.get_client_traffic(email)
    if not t:
        await message.answer(f"کلاینتی با ایمیل {email} پیدا نشد.")
        return
    cur_total = t.get("total", 0)
    skipped_gb = False
    if cur_total == 0:
        new_total = 0
        skipped_gb = add_gb > 0
    else:
        new_total = cur_total + add_gb * 1024**3
    now_ms = int(time.time() * 1000)
    cur_exp = t.get("expiryTime", 0)
    if add_days:
        base = cur_exp if cur_exp and cur_exp > now_ms else now_ms
        new_exp = base + add_days * 86400 * 1000
    else:
        new_exp = cur_exp
    body = {"email": email, "totalGB": new_total, "expiryTime": new_exp, "enable": True}
    flow = x.client_flow()
    if flow:
        body["flow"] = flow
    try:
        x._request("POST", f"/panel/api/clients/update/{email}", json=body)
        msg = f"✅ {email}: {add_days} روز اضافه شد."
        if skipped_gb:
            msg += " (این کلاینت نامحدود بود؛ حجم تغییر نکرد.)"
        elif add_gb:
            msg = f"✅ {email}: {add_gb} گیگ و {add_days} روز اضافه شد."
        await message.answer(msg)
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")


# ---------------------------------------------------------------- per-client extend/toggle/delete

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


@router.message(F.text == "🔒 مسدود/فعال کلاینت")
async def ask_toggle_client(message: Message):
    if not _admin(message):
        return
    await clientlist.show_action_list(message, "toggle")


@router.message(F.text == "🗑 حذف کلاینت")
async def ask_delete_client(message: Message):
    if not _admin(message):
        return
    await clientlist.show_action_list(message, "delete")


# ---------------------------------------------------------------- bulk renew / bulk delete expired

@router.message(F.text == "🔄 تمدید انبوه")
async def ask_bulk_renew(message: Message):
    if not _admin(message):
        return
    _pending[message.from_user.id] = {"action": "bulk_renew"}
    await message.answer("همه‌ی کلاینت‌های فعال چند روز تمدید بشن؟ فقط عدد بفرست. /cancel برای لغو.")


async def _do_bulk_renew(message: Message, days: int):
    x = XUIClient()
    try:
        clients = _list_clients(x)
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خطا: {e}")
        return
    now_ms = int(time.time() * 1000)
    renewed, failed = 0, []
    flow = x.client_flow()
    for c in clients:
        em = c.get("email")
        t = x.get_client_traffic(em) or {}
        exp = t.get("expiryTime", 0)
        if exp and exp < now_ms:
            continue  # expired clients go through bulk delete, not bulk renew
        base = exp if exp and exp > now_ms else now_ms
        body = {"email": em, "totalGB": t.get("total", 0), "expiryTime": base + days * 86400 * 1000,
                "enable": True}
        if flow:
            body["flow"] = flow
        try:
            x._request("POST", f"/panel/api/clients/update/{em}", json=body)
            renewed += 1
        except XUIError as e:
            failed.append(f"{em}: {e}")
    msg = f"✅ {renewed} کلاینت فعال {days} روز تمدید شد."
    if failed:
        msg += "\n\n❌ ناموفق:\n" + "\n".join(failed[:5])
    await message.answer(msg)


@router.message(F.text == "🗑 حذف انبوه (منقضی‌شده‌ها)")
async def bulk_delete_expired(message: Message):
    if not _admin(message):
        return
    x = XUIClient()
    try:
        clients = _list_clients(x)
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خطا: {e}")
        return
    now_ms = time.time() * 1000
    expired = []
    for c in clients:
        em = c.get("email")
        t = x.get_client_traffic(em) or {}
        exp = t.get("expiryTime", 0)
        if exp and exp < now_ms:
            expired.append(em)
    if not expired:
        await message.answer("هیچ کلاینت منقضی‌شده‌ای پیدا نشد.")
        return
    _pending[message.from_user.id] = {"action": "bulk_delete_confirm", "emails": expired}
    preview = "\n".join(expired[:15]) + ("\n…" if len(expired) > 15 else "")
    await message.answer(
        f"{len(expired)} کلاینت منقضی پیدا شد:\n{preview}\n\n"
        "برای حذف قطعی «بله» رو بفرست. /cancel برای لغو."
    )


async def _do_bulk_delete(message: Message, emails: list[str]):
    x = XUIClient()
    deleted, failed = 0, []
    for em in emails:
        try:
            x.delete_client(inbound_id=config.XUI_INBOUND_ID, client_uuid="", email=em)
            deleted += 1
        except XUIError as e:
            failed.append(f"{em}: {e}")
    msg = f"✅ {deleted} کلاینت حذف شد."
    if failed:
        msg += "\n\n❌ ناموفق:\n" + "\n".join(failed[:5])
    await message.answer(msg)


# ---------------------------------------------------------------- support inbox (relayed from the sales bot)
# A customer's support messages arrive here relayed from the sales bot
# (utils/support_relay.py), each with a "↩️ پاسخ به این گفتگو" button.
# Tapping it makes this admin's messages go to that customer until they
# end the chat — no native-reply gesture to remember or miss.

@router.callback_query(F.data.startswith("supreply:"))
async def support_reply_button(callback: CallbackQuery):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return
    target_tg_id = int(callback.data.split(":", 1)[1])
    support_relay.set_active_target(callback.from_user.id, target_tg_id)
    await callback.answer()
    await callback.message.answer(
        f"💬 وارد گفتگو با مشتری {target_tg_id} شدی — هر چی بفرستی مستقیم براش می‌ره.\n"
        f"برای پایان «{support_relay.ADMIN_EXIT_BUTTON}» رو بزن.",
        reply_markup=support_relay.admin_chat_keyboard(),
    )


@router.message(F.text == support_relay.ADMIN_EXIT_BUTTON)
async def end_admin_support_chat(message: Message):
    if not _admin(message):
        return
    support_relay.end_active_target(message.from_user.id)
    await message.answer("گفتگو با مشتری تموم شد.", reply_markup=MENU)


def _is_admin_support_chat(message: Message) -> bool:
    if not message.text or not _admin(message):
        return False
    if support_relay.get_active_target(message.from_user.id) is None:
        return False
    if message.text.startswith("/") or message.text in _KNOWN_MENU_TEXTS:
        support_relay.end_active_target(message.from_user.id)
        return False
    return True


@router.message(_is_admin_support_chat)
async def relay_admin_support_chat(message: Message):
    result = await support_relay.send_admin_reply(message.from_user.id, message.text)
    await message.answer(result)


# ---------------------------------------------------------------- pending-action dispatch
# Only fires when this admin has an open multi-step flow — everything else
# (including menu button text that doesn't match) falls through untouched
# because this handler is filtered out, not because it swallows and ignores.

def _has_pending(message: Message) -> bool:
    return bool(message.text) and not message.text.startswith("/") and message.from_user.id in _pending


@router.message(_has_pending)
async def handle_pending(message: Message):
    pending = _pending[message.from_user.id]
    action = pending["action"]
    text = message.text.strip()

    # Multi-stage flows manage their own _pending updates and pop themselves
    # once their last stage is reached.
    if action == "new_panel":
        await _new_panel_step(message, pending)
        return
    if action == "iran_ssh":
        await _iran_ssh_step(message, pending)
        return
    if action == "card_setup":
        await _card_setup_step(message, pending)
        return
    if action == "new_client":
        await _new_client_step(message, pending)
        return
    if action == "bulk_create":
        await _bulk_create_step(message, pending)
        return
    if action == "increase":
        await _increase_step(message, pending)
        return
    if action == "extend_client":
        if pending["stage"] == "email":
            _pending[message.from_user.id] = {"action": "extend_client", "stage": "days", "email": text}
            await message.answer("چند روز تمدید بشه؟ فقط عدد بفرست.")
        else:
            _pending.pop(message.from_user.id, None)
            try:
                days = int(text)
            except ValueError:
                await message.answer("عدد نامعتبر. از ⏳ تمدید کلاینت دوباره شروع کن.")
                return
            await _do_extend_client(message, pending["email"], days)
        return

    # Single-stage flows: pop, then dispatch.
    _pending.pop(message.from_user.id, None)
    if action == "change_dest":
        await _apply_new_dest(message, text)
    elif action == "change_port":
        await _apply_new_port(message, text)
    elif action == "cloudflare_token":
        await _apply_cloudflare_token(message, message.text)
    elif action == "github_token":
        await _apply_github_token(message, message.text)
    elif action == "ws_tls_setup":
        await _do_ws_tls_setup(message, text)
    elif action == "broadcast":
        await _do_broadcast(message, message.text)
    elif action == "unban_ip":
        await _do_unban(message, text)
    elif action == "bulk_renew":
        try:
            days = int(text)
        except ValueError:
            await message.answer("عدد نامعتبر.")
            return
        await _do_bulk_renew(message, days)
    elif action == "bulk_delete_confirm":
        if text in ("بله", "بله.", "yes", "Yes"):
            await _do_bulk_delete(message, pending["emails"])
        else:
            await message.answer("لغو شد؛ چیزی حذف نشد.")
