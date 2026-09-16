#!/usr/bin/env bash
# Installs ONLY the Telegram sales bot (no X-UI/Xray here) — for a second,
# non-Iran server that can actually reach api.telegram.org. This bot talks
# to the X-UI panel on your Iran VPN server over the internet using its
# public IP and API token (both already created there).
#
# Usage:
#   BOT_TOKEN=... ADMIN_IDS=... CARD_NUMBER=... CARD_OWNER=... \
#   XUI_BASE_URL=http://VPN_SERVER_IP:PANEL_PORT/WEB_BASE_PATH \
#   XUI_API_TOKEN=... XUI_INBOUND_ID=... XUI_PUBLIC_HOST=VPN_SERVER_IP \
#   bash deploy-bot-only.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run as root" >&2; exit 1; fi

: "${BOT_TOKEN:?Set BOT_TOKEN=...}"
: "${ADMIN_IDS:?Set ADMIN_IDS=your_numeric_telegram_id}"
: "${CARD_NUMBER:?Set CARD_NUMBER=...}"
: "${CARD_OWNER:?Set CARD_OWNER=...}"
: "${XUI_BASE_URL:?Set XUI_BASE_URL=http://VPN_SERVER_IP:PANEL_PORT/WEB_BASE_PATH}"
: "${XUI_API_TOKEN:?Set XUI_API_TOKEN=... (from the VPN server's /etc/x-ui/install-result.env)}"
: "${XUI_INBOUND_ID:?Set XUI_INBOUND_ID=... (printed by setup_inbound.py on the VPN server)}"
: "${XUI_PUBLIC_HOST:?Set XUI_PUBLIC_HOST=the VPN server's public IP (for building client links)}"

APP_DIR=/opt/hermes-vpn-bot

echo "==> System packages"
# This box only makes outbound connections (to Telegram and to the VPN
# server's panel) — nothing needs to be opened inbound here, so we don't
# touch the local firewall (ufw/firewalld) or the cloud provider's
# security group/list at all.
if command -v apt-get >/dev/null 2>&1; then
  apt-get update -y
  apt-get install -y python3-venv python3-pip curl
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y python3 python3-pip curl
elif command -v yum >/dev/null 2>&1; then
  yum install -y python3 python3-pip curl
else
  echo "No supported package manager found (apt-get/dnf/yum)." >&2
  exit 1
fi

echo "==> Writing bot source to $APP_DIR"
mkdir -p "$APP_DIR/bot"

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/config.py" << 'PYEOF'
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@your_support")
BOT_NAME = os.getenv("BOT_NAME", "VPN Store")

# Real business bank card — set these in .env, never hardcode real numbers here.
CARD_NUMBER = os.getenv("CARD_NUMBER", "0000-0000-0000-0000")
CARD_OWNER = os.getenv("CARD_OWNER", "SET CARD_OWNER IN .env")

XUI_BASE_URL = os.getenv("XUI_BASE_URL", "http://127.0.0.1:2053")
# Preferred auth: an API token (Authorization: Bearer ...) — newer 3x-ui
# versions print one at install time and reject cookie-session /login for
# non-browser clients. username/password are kept as a fallback for older
# panel versions that only support the cookie-login flow.
XUI_API_TOKEN = os.getenv("XUI_API_TOKEN", "")
XUI_USERNAME = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "admin")
XUI_INBOUND_ID = int(os.getenv("XUI_INBOUND_ID", "1"))
# Public host/IP clients connect to — usually different from XUI_BASE_URL,
# which points at 127.0.0.1 so the panel API stays localhost-only.
XUI_PUBLIC_HOST = os.getenv("XUI_PUBLIC_HOST", "")
# Optional: base URL for a subscription link if you expose one via the panel/sub server.
XUI_SUB_BASE_URL = os.getenv("XUI_SUB_BASE_URL", "")

DB_PATH = os.getenv("DB_PATH", "bot.db")

TRIAL_MB = int(os.getenv("TRIAL_MB", "200"))
TRIAL_HOURS = int(os.getenv("TRIAL_HOURS", "1"))

# Edit prices/plans freely. gb=0 means unlimited data (only time-limited).
PLANS = [
    {"key": "p10_30", "label": "10 گیگ / 30 روز", "gb": 10, "days": 30, "price": 40000},
    {"key": "p20_30", "label": "20 گیگ / 30 روز", "gb": 20, "days": 30, "price": 60000},
    {"key": "p30_30", "label": "30 گیگ / 30 روز", "gb": 30, "days": 30, "price": 85000},
    {"key": "p50_30", "label": "50 گیگ / 30 روز", "gb": 50, "days": 30, "price": 130000},
    {"key": "p100_30", "label": "100 گیگ / 30 روز", "gb": 100, "days": 30, "price": 180000},
]

PLANS_BY_KEY = {p["key"]: p for p in PLANS}
PYEOF

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/db.py" << 'PYEOF'
import sqlite3
import time
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id INTEGER PRIMARY KEY,
    username TEXT,
    created_at INTEGER,
    trial_used INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id INTEGER,
    plan_key TEXT,
    gb INTEGER,
    days INTEGER,
    base_price INTEGER,
    amount INTEGER,
    status TEXT DEFAULT 'pending',      -- pending | awaiting_review | approved | rejected
    xui_email TEXT,
    renew_target_email TEXT,            -- set when this order is a renewal of an existing client
    created_at INTEGER
);

CREATE TABLE IF NOT EXISTS clients (
    xui_email TEXT PRIMARY KEY,
    tg_id INTEGER,
    uuid TEXT,
    gb INTEGER,
    expiry_time INTEGER,
    created_at INTEGER
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def upsert_user(tg_id: int, username: str | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO users (tg_id, username, created_at) VALUES (?, ?, ?)"
            "ON CONFLICT(tg_id) DO UPDATE SET username=excluded.username",
            (tg_id, username, int(time.time())),
        )


def has_used_trial(tg_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT trial_used FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        return bool(row and row["trial_used"])


def mark_trial_used(tg_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET trial_used=1 WHERE tg_id=?", (tg_id,))


def create_order(
    tg_id: int,
    plan_key: str,
    gb: int,
    days: int,
    base_price: int,
    amount: int,
    renew_target_email: str | None = None,
) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO orders (tg_id, plan_key, gb, days, base_price, amount, status, renew_target_email, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_review', ?, ?)",
            (tg_id, plan_key, gb, days, base_price, amount, renew_target_email, int(time.time())),
        )
        return cur.lastrowid


def get_order(order_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()


def set_order_status(order_id: int, status: str, xui_email: str | None = None):
    with get_conn() as conn:
        if xui_email is not None:
            conn.execute("UPDATE orders SET status=?, xui_email=? WHERE id=?", (status, xui_email, order_id))
        else:
            conn.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))


def amount_in_use(amount: int) -> bool:
    """True if another order is currently awaiting review with the same exact amount."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM orders WHERE amount=? AND status='awaiting_review'", (amount,)
        ).fetchone()
        return row is not None


def save_client(xui_email: str, tg_id: int, client_uuid: str, gb: int, expiry_time: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO clients (xui_email, tg_id, uuid, gb, expiry_time, created_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(xui_email) DO UPDATE SET gb=excluded.gb, expiry_time=excluded.expiry_time",
            (xui_email, tg_id, client_uuid, gb, expiry_time, int(time.time())),
        )


def get_clients_for_user(tg_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM clients WHERE tg_id=?", (tg_id,)).fetchall()


def report_last_24h():
    since = int(time.time()) - 24 * 3600
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total "
            "FROM orders WHERE status='approved' AND created_at >= ?",
            (since,),
        ).fetchone()
        return row["cnt"], row["total"]
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/__init__.py" << 'PYEOF'

PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/admin.py" << 'PYEOF'
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

import config
import db

router = Router()


def _is_admin(message: Message) -> bool:
    return message.from_user.id in config.ADMIN_IDS


@router.message(Command("report"))
async def report(message: Message):
    if not _is_admin(message):
        return
    count, total = db.report_last_24h()
    await message.answer(
        "📋 گزارش تطبیق مالی — 24 ساعت گذشته\n\n"
        f"تعداد سفارش تایید شده: {count}\n"
        f"جمع مبلغ: {total:,} تومان"
    )


@router.message(F.text == "📦 خرید عمده")
async def bulk_buy(message: Message):
    await message.answer(
        "برای خرید عمده (چند اکانت با تخفیف) لطفاً مستقیم با پشتیبانی صحبت کن:\n"
        f"{config.SUPPORT_USERNAME}"
    )
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/buy.py" << 'PYEOF'
import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, Message

import config
import db
from keyboards import MAIN_MENU, admin_review_keyboard, plans_keyboard
from utils.pricing import unique_amount
from utils.delivery import send_service_pack_to
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)

# tg_id -> pending order_id waiting for a receipt photo
_awaiting_receipt: dict[int, int] = {}


@router.message(F.text == "🛒 خرید سرویس")
async def buy_menu(message: Message):
    await message.answer("یکی از پلن‌ها رو انتخاب کن:", reply_markup=plans_keyboard("buy"))


@router.callback_query(F.data.startswith("buy:"))
async def choose_plan(callback: CallbackQuery, bot: Bot):
    plan_key = callback.data.split(":", 1)[1]
    plan = config.PLANS_BY_KEY.get(plan_key)
    if not plan:
        await callback.answer("پلن پیدا نشد", show_alert=True)
        return

    amount = unique_amount(plan["price"])
    order_id = db.create_order(
        tg_id=callback.from_user.id,
        plan_key=plan_key,
        gb=plan["gb"],
        days=plan["days"],
        base_price=plan["price"],
        amount=amount,
    )
    _awaiting_receipt[callback.from_user.id] = order_id

    text = (
        f"پلن انتخابی: {plan['label']}\n\n"
        f"مبلغ قابل پرداخت — دقیقاً همین عدد (روش بزن تا کپی شه):\n"
        f"💰 {amount:,} تومان\n\n"
        f"شماره کارت (روش بزن تا کپی شه):\n"
        f"💳 {config.CARD_NUMBER}\n"
        f"👤 به نام: {config.CARD_OWNER}\n\n"
        "بعد از واریز، رسید یا اسکرین‌شات پرداخت رو همینجا بفرست تا سرویس فعال بشه.\n"
        f"(شماره سفارش: #{order_id})"
    )
    await callback.message.answer(text)
    await callback.answer()


@router.message(F.photo)
async def receive_receipt(message: Message, bot: Bot):
    order_id = _awaiting_receipt.get(message.from_user.id)
    if not order_id:
        return  # not in the middle of a purchase, ignore

    order = db.get_order(order_id)
    if not order or order["status"] != "awaiting_review":
        return

    photo = message.photo[-1]
    caption = (
        f"🧾 رسید جدید برای سفارش #{order_id}\n"
        f"کاربر: @{message.from_user.username or message.from_user.id} (id: {message.from_user.id})\n"
        f"پلن: {order['gb']} گیگ / {order['days']} روز\n"
        f"مبلغ: {order['amount']:,} تومان"
    )
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_photo(
                admin_id, photo.file_id, caption=caption, reply_markup=admin_review_keyboard(order_id)
            )
        except Exception:
            log.exception("failed to notify admin %s", admin_id)

    await message.answer("رسید شما دریافت شد و برای بررسی ارسال شد. لطفاً چند دقیقه صبر کن.")


@router.callback_query(F.data.startswith("approve:"))
async def approve_order(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return

    order_id = int(callback.data.split(":", 1)[1])
    order = db.get_order(order_id)
    if not order:
        await callback.answer("سفارش پیدا نشد", show_alert=True)
        return
    if order["status"] != "awaiting_review":
        await callback.answer("این سفارش قبلاً پردازش شده", show_alert=True)
        return

    xui = XUIClient()
    try:
        if order["renew_target_email"]:
            email = order["renew_target_email"]
            existing = db.get_clients_for_user(order["tg_id"])
            existing_uuid = next((c["uuid"] for c in existing if c["xui_email"] == email), None)
            if not existing_uuid:
                raise XUIError(f"no local client record for {email}")
            client = xui.update_client(existing_uuid, email, gb=order["gb"], days=order["days"])
        else:
            email = f"user{order['tg_id']}-order{order_id}"
            client = xui.add_client(email=email, gb=order["gb"], days=order["days"])
        link = xui.build_vless_link(client["uuid"], email)
        sub_url = xui.get_sub_url(email)
    except Exception as e:
        log.exception("XUI provisioning failed for order %s", order_id)
        await callback.message.edit_caption(
            caption=(callback.message.caption or "")
            + f"\n\n⚠️ خطا در ساخت اکانت روی پنل — دستی بررسی کن.\n{type(e).__name__}: {e}"
        )
        await callback.answer(f"خطا: {e}"[:200], show_alert=True)
        return

    db.save_client(email, order["tg_id"], client["uuid"], order["gb"], client["expiry_time"])
    db.set_order_status(order_id, "approved", xui_email=email)
    _awaiting_receipt.pop(order["tg_id"], None)

    await send_service_pack_to(
        bot, order["tg_id"], email, link, sub_url,
        header="✅ پرداخت تایید شد و سرویس شما فعال شد!",
    )
    await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n✅ تایید شد")
    await callback.answer("تایید شد و اکانت ساخته شد")


@router.callback_query(F.data.startswith("reject:"))
async def reject_order(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in config.ADMIN_IDS:
        await callback.answer("فقط ادمین", show_alert=True)
        return

    order_id = int(callback.data.split(":", 1)[1])
    order = db.get_order(order_id)
    if not order or order["status"] != "awaiting_review":
        await callback.answer("سفارش پیدا نشد یا قبلاً پردازش شده", show_alert=True)
        return

    db.set_order_status(order_id, "rejected")
    _awaiting_receipt.pop(order["tg_id"], None)

    await bot.send_message(
        order["tg_id"], "❌ پرداخت شما تایید نشد. اگر فکر می‌کنی اشتباهی رخ داده با پشتیبانی تماس بگیر."
    )
    await callback.message.edit_caption(caption=(callback.message.caption or "") + "\n\n❌ رد شد")
    await callback.answer("رد شد")
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/renew.py" << 'PYEOF'
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import config
import db
from keyboards import plans_keyboard
from utils.pricing import unique_amount
from handlers.buy import _awaiting_receipt  # reuse the same pending-receipt map

router = Router()


@router.message(F.text == "🔄 تمدید سرویس")
async def renew_menu(message: Message):
    clients = db.get_clients_for_user(message.from_user.id)
    if not clients:
        await message.answer("سرویس فعالی برای تمدید پیدا نشد. اول یک پلن بخر.")
        return

    if len(clients) == 1:
        await message.answer(
            "یکی از پلن‌ها رو برای تمدید انتخاب کن:",
            reply_markup=plans_keyboard(f"renew:{clients[0]['xui_email']}"),
        )
        return

    rows = [
        [InlineKeyboardButton(text=c["xui_email"], callback_data=f"renewpick:{c['xui_email']}")]
        for c in clients
    ]
    await message.answer("کدوم سرویس رو می‌خوای تمدید کنی؟", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("renewpick:"))
async def renew_pick(callback: CallbackQuery):
    email = callback.data.split(":", 1)[1]
    await callback.message.answer("یکی از پلن‌ها رو انتخاب کن:", reply_markup=plans_keyboard(f"renew:{email}"))
    await callback.answer()


@router.callback_query(F.data.startswith("renew:"))
async def choose_renew_plan(callback: CallbackQuery):
    _, target_email, plan_key = callback.data.split(":", 2)
    plan = config.PLANS_BY_KEY.get(plan_key)
    if not plan:
        await callback.answer("پلن پیدا نشد", show_alert=True)
        return

    amount = unique_amount(plan["price"])
    order_id = db.create_order(
        tg_id=callback.from_user.id,
        plan_key=plan_key,
        gb=plan["gb"],
        days=plan["days"],
        base_price=plan["price"],
        amount=amount,
        renew_target_email=target_email,
    )
    _awaiting_receipt[callback.from_user.id] = order_id

    text = (
        f"تمدید سرویس: {plan['label']}\n\n"
        f"مبلغ قابل پرداخت — دقیقاً همین عدد:\n💰 {amount:,} تومان\n\n"
        f"شماره کارت:\n💳 {config.CARD_NUMBER}\n👤 به نام: {config.CARD_OWNER}\n\n"
        "بعد از واریز، رسید رو همینجا بفرست.\n"
        f"(شماره سفارش: #{order_id})"
    )
    await callback.message.answer(text)
    await callback.answer()
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/start.py" << 'PYEOF'
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

import config
import db
from keyboards import MAIN_MENU

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"👋 به {config.BOT_NAME} خوش اومدی!\n\n"
        "از منوی پایین یکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=MAIN_MENU,
    )


@router.message(lambda m: m.text == "🆘 پشتیبانی")
async def support(message: Message):
    await message.answer(f"برای پشتیبانی پیام بده: {config.SUPPORT_USERNAME}")
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/status.py" << 'PYEOF'
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
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/trial.py" << 'PYEOF'
import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import Message

import config
import db
from utils.delivery import send_service_pack
from xui_client import XUIClient

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == "🧪 تست")
async def trial(message: Message, bot: Bot):
    tg_id = message.from_user.id
    # Admins run this to check the service itself, so the one-per-user limit
    # would stop them testing after the first try.
    is_admin = tg_id in config.ADMIN_IDS
    if not is_admin and db.has_used_trial(tg_id):
        await message.answer("شما قبلاً از سرویس تست استفاده کردی. برای ادامه یکی از پلن‌ها رو بخر.")
        return

    email = f"trial{tg_id}-{int(time.time())}"
    try:
        xui = XUIClient()
        client = xui.add_client(email=email, mb=config.TRIAL_MB, hours=config.TRIAL_HOURS)
        link = xui.build_vless_link(client["uuid"], email)
        sub_url = xui.get_sub_url(email)
    except Exception as e:
        log.exception("trial provisioning failed for %s", tg_id)
        detail = f"\n\n`{type(e).__name__}: {e}`" if tg_id in config.ADMIN_IDS else ""
        await message.answer(
            "خطا در ساخت اکانت تست، لطفاً بعداً دوباره امتحان کن یا با پشتیبانی تماس بگیر." + detail,
            parse_mode="Markdown" if detail else None,
        )
        return

    db.save_client(email, tg_id, client["uuid"], 0, client["expiry_time"])
    if not is_admin:
        db.mark_trial_used(tg_id)

    await send_service_pack(
        message, email, link, sub_url,
        header=f"🧪 اکانت تست ساخته شد ({config.TRIAL_MB} مگابایت / {config.TRIAL_HOURS} ساعت)",
    )
PYEOF
cat > "$APP_DIR/bot/handlers/ops.py" << 'PYEOF'
"""Operator commands, so running the service never requires an SSH session.

The phone keeps dropping SSH; the bot does not. Everything here is admin-only
and answers in Telegram.
"""
import email.utils
import json
import os
import logging
import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import config
from utils.x25519 import public_from_private
from xui_client import XUIClient, XUIError

router = Router()
log = logging.getLogger(__name__)

# Set once, when this module is first imported by a process — lets /whoami
# prove whether a reply came from the process just restarted or a stale one
# still polling Telegram alongside it (two processes sharing one bot token
# behave exactly like a bot that "sometimes doesn't answer": Telegram hands
# each update to whichever one asks first, so replies look random).
_LOADED_AT = time.time()
_PID = os.getpid()


@router.error()
async def report_crashes(event):
    """Catch anything a handler above missed, so an admin command never fails
    in total silence — which is exactly what happened when /testtunnel's
    import raised before its first reply (see: forgetting a file in FILES)."""
    log.exception("unhandled error in ops handler", exc_info=event.exception)
    update = event.update
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg and msg.chat.id in config.ADMIN_IDS:
        try:
            await msg.answer(f"❌ خطای پیش‌بینی‌نشده: {type(event.exception).__name__}: {event.exception}")
        except Exception:
            pass
    return True

HELP = (
    "🛠 دستورهای مدیریت:\n\n"
    "/diag — بررسی کامل سرور و پنل\n"
    "/clients — فهرست کلاینت‌ها و وضعیتشان\n"
    "/fixflow — اصلاح flow همه‌ی کلاینت‌های قدیمی\n"
    "/fixkeys — بازتولید کلید Reality وقتی جفت نیست\n"
    "/testtunnel — تست اتصال واقعی از سرور (بدون نیاز به گوشی)\n"
    "/restartxray — ری‌استارت هسته‌ی Xray\n"
    "/update — دریافت آخرین نسخه‌ی کد و ری‌استارت\n"
    "/whoami — کدام پردازش دارد جواب می‌دهد (تشخیص پردازش‌های تکراری)\n"
    "/ops — همین راهنما"
)


def _admin(message: Message) -> bool:
    return message.from_user.id in config.ADMIN_IDS


def _size(n: int) -> str:
    return f"{n / 1024**3:.2f}GB" if n >= 1024**3 else f"{n / 1024**2:.0f}MB"


@router.message(Command("ops"))
async def ops_help(message: Message):
    if _admin(message):
        await message.answer(HELP)


@router.message(Command("whoami"))
async def whoami(message: Message):
    """Which process actually answered — the one thing needed to catch a
    stray duplicate bot process still running outside systemd."""
    if not _admin(message):
        return
    import subprocess

    age = time.time() - _LOADED_AT
    lines = [f"PID: {_PID}", f"این پردازش {age:.0f} ثانیه پیش بالا آمده", f"تعداد فایل در /update: {len(FILES)}"]
    try:
        out = subprocess.run(["pgrep", "-af", "bot/main.py"], capture_output=True, text=True, timeout=5).stdout
        # pgrep -f matches the whole command line, so a shell wrapper that
        # merely mentions this path (like the one running this very check)
        # matches too; keep only lines whose command actually is a python
        # interpreter, not something that just quotes the path in passing.
        def _is_python_proc(line: str) -> bool:
            parts = line.split(None, 1)
            if len(parts) < 2:
                return False
            argv0 = parts[1].split()[0] if parts[1].split() else ""
            return "python" in os.path.basename(argv0)

        procs = [l for l in out.splitlines() if l.strip() and _is_python_proc(l)]
        lines.append(f"\nهمه‌ی پردازش‌های main.py روی این سرور ({len(procs)}):")
        lines += [f"  {p}" for p in procs] or ["  (هیچ‌کدام با pgrep پیدا نشد)"]
        if len(procs) > 1:
            lines.append("\n⚠️ بیش از یک پردازش در حال اجراست — همین باعث جواب‌های نامنظم می‌شود.")
    except Exception as e:
        lines.append(f"\n(بررسی پردازش‌ها ممکن نشد: {e})")
    await message.answer("\n".join(lines))


@router.message(Command("diag"))
async def diag(message: Message):
    if not _admin(message):
        return
    await message.answer("⏳ در حال بررسی…")
    lines = []
    x = XUIClient()

    # Reality authenticates against a timestamp, so a drifted server clock
    # rejects every client in a way that looks like a healthy connection.
    try:
        import requests

        r = requests.get(x.base_url + "/", timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        served = r.headers.get("Date")
        skew = email.utils.mktime_tz(email.utils.parsedate_tz(served)) - time.time()
        lines.append(f"{'✅' if abs(skew) <= 90 else '❌'} ساعت سرور: اختلاف {skew:+.0f} ثانیه")
    except Exception as e:
        lines.append(f"⚠️ ساعت سرور: قابل بررسی نبود ({type(e).__name__})")

    try:
        inbound = x.get_inbound()
        stream = inbound.get("streamSettings")
        stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
        reality = stream.get("realitySettings") or {}
        settings = inbound.get("settings")
        settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
        clients = settings.get("clients") or []
        lines.append(f"✅ اینباند {inbound.get('id')} روی پورت {inbound.get('port')}"
                     f" — {inbound.get('protocol')}/{stream.get('security')}")
        lines.append(f"   دامنه: {(reality.get('serverNames') or ['?'])[0]}")
        lines.append(f"   کلاینت‌ها: {len(clients)}")

        # The link carries a public key the panel stores separately from the
        # private key Xray authenticates with; if they ever fell out of step
        # every client fails and is handed to the fallback site.
        priv = reality.get("privateKey") or ""
        shown = (reality.get("settings") or {}).get("publicKey") or ""
        if priv:
            try:
                derived = public_from_private(priv)
                if derived == shown.strip().rstrip("="):
                    lines.append("✅ کلید عمومی با کلید خصوصی جفت است")
                else:
                    lines.append("❌ کلید عمومی با کلید خصوصی جفت نیست!")
                    lines.append(f"   در لینک: {shown[:20]}…")
                    lines.append(f"   درست  : {derived[:20]}…")
                    lines.append("   با /fixkeys درستش کن")
            except ValueError as e:
                lines.append(f"⚠️ بررسی کلید ممکن نشد: {e}")
        else:
            lines.append("⚠️ پنل کلید خصوصی را برنمی‌گرداند (قابل بررسی نیست)")

        want = x.client_flow()
        missing = [c.get("email") for c in clients if (c.get("flow") or "") != want]
        if want and missing:
            lines.append(f"❌ {len(missing)} کلاینت flow اشتباه دارند (باید {want} باشد)")
            lines.append("   با /fixflow درستشان کن")
        else:
            lines.append(f"✅ flow همه‌ی کلاینت‌ها درست است ({want or 'بدون flow'})")
    except (XUIError, ValueError) as e:
        lines.append(f"❌ خواندن اینباند ناموفق: {e}")

    try:
        logs = x._request("POST", "/panel/api/server/xraylogs/50") or []
        lines.append(f"{'✅' if logs else '⚠️'} رکوردهای اتصال اخیر: {len(logs)}")
        if not logs:
            lines.append("   یعنی هیچ کلاینتی تا الان پذیرفته نشده")
    except XUIError as e:
        lines.append(f"⚠️ لاگ Xray: {e}")

    await message.answer("🔎 نتیجه بررسی:\n\n" + "\n".join(lines))


@router.message(Command("clients"))
async def clients_cmd(message: Message):
    if not _admin(message):
        return
    x = XUIClient()
    try:
        inbound = x.get_inbound()
        settings = inbound.get("settings")
        settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
        clients = settings.get("clients") or []
    except (XUIError, ValueError) as e:
        await message.answer(f"خطا: {e}")
        return

    if not clients:
        await message.answer("هیچ کلاینتی روی اینباند نیست.")
        return

    now = time.time() * 1000
    rows = []
    for c in clients[-20:]:
        em = c.get("email", "?")
        t = x.get_client_traffic(em) or {}
        exp = t.get("expiryTime", 0)
        state = "منقضی" if exp and exp < now else "فعال"
        rows.append(f"• {em}\n   {_size(t.get('up',0)+t.get('down',0))} از "
                    f"{_size(t.get('total',0)) if t.get('total') else '∞'} — {state}"
                    f" — flow: {c.get('flow') or 'ندارد'}")
    await message.answer("👥 کلاینت‌ها:\n\n" + "\n".join(rows))


@router.message(Command("fixflow"))
async def fixflow(message: Message):
    if not _admin(message):
        return
    x = XUIClient()
    want = x.client_flow()
    if not want:
        await message.answer("این اینباند flow نمی‌خواهد؛ کاری لازم نیست.")
        return

    try:
        inbound = x.get_inbound()
        settings = inbound.get("settings")
        settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
        clients = settings.get("clients") or []
    except (XUIError, ValueError) as e:
        await message.answer(f"خطا: {e}")
        return

    fixed, failed = 0, []
    for c in clients:
        if (c.get("flow") or "") == want:
            continue
        em = c.get("email")
        t = x.get_client_traffic(em) or {}
        body = {"email": em, "totalGB": t.get("total", 0),
                "expiryTime": t.get("expiryTime", 0), "enable": True, "flow": want}
        try:
            x._request("POST", f"/panel/api/clients/update/{em}", json=body)
            fixed += 1
        except XUIError as e:
            failed.append(f"{em}: {e}")

    msg = f"✅ {fixed} کلاینت اصلاح شد (flow={want})."
    if failed:
        msg += "\n\n❌ ناموفق:\n" + "\n".join(failed[:5])
    msg += "\n\nحالا لینک‌ها را دوباره بگیر (♻️ دریافت دوباره لینک)."
    await message.answer(msg)


@router.message(Command("restartxray"))
async def restart_xray(message: Message):
    if not _admin(message):
        return
    try:
        XUIClient()._request("POST", "/panel/api/server/restartXrayService")
        await message.answer("✅ Xray ری‌استارت شد.")
    except XUIError as e:
        await message.answer(f"❌ ناموفق: {e}")


@router.message(Command("fixkeys"))
async def fixkeys(message: Message):
    """Write back the public key that actually matches the private key."""
    if not _admin(message):
        return
    x = XUIClient()
    try:
        inbound = x.get_inbound()
        stream = inbound.get("streamSettings")
        stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
        reality = stream.get("realitySettings") or {}
        priv = reality.get("privateKey") or ""
        if not priv:
            await message.answer("پنل کلید خصوصی را برنمی‌گرداند؛ از خود پنل کلیدها را بازتولید کن.")
            return
        derived = public_from_private(priv)
        settings_block = reality.get("settings") or {}
        if settings_block.get("publicKey", "").strip().rstrip("=") == derived:
            await message.answer("کلیدها از قبل جفت‌اند؛ کاری لازم نیست.")
            return

        settings_block["publicKey"] = derived
        reality["settings"] = settings_block
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
            f"✅ کلید عمومی اصلاح شد:\n`{derived}`\n\n"
            "Xray ری‌استارت شد. حالا یک لینک تازه بگیر (🧪 تست).",
            parse_mode="Markdown")
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ ناموفق: {e}")


RAW = ("https://raw.githubusercontent.com/mehranbehnam/desktop-tutorial/"
       "refs/heads/claude/iran-vpn-turkey-d2hbvg/hermes-vpn-bot")
FILES = [
    "bot/config.py", "bot/db.py", "bot/keyboards.py", "bot/main.py", "bot/devbot_main.py",
    "bot/xui_client.py",
    "bot/handlers/__init__.py", "bot/handlers/admin.py", "bot/handlers/buy.py",
    "bot/handlers/renew.py", "bot/handlers/start.py", "bot/handlers/status.py",
    "bot/handlers/trial.py", "bot/handlers/ops.py", "bot/handlers/devmenu.py",
    "bot/utils/__init__.py", "bot/utils/pricing.py", "bot/utils/delivery.py",
    "bot/utils/x25519.py", "bot/utils/tunnel_test.py",
]


@router.message(Command("update"))
async def update(message: Message):
    """Pull the latest code and restart, so fixes never need an SSH session.

    Everything is staged and compile-checked first; a half-downloaded file
    would otherwise leave the bot unable to start, with no way back in.
    """
    if not _admin(message):
        return
    import py_compile
    import shutil
    import subprocess
    import tempfile
    import urllib.request

    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    install_dir = os.path.dirname(bot_dir)
    await message.answer("⏳ در حال دریافت آخرین نسخه…")

    staged, errors = {}, []
    with tempfile.TemporaryDirectory() as tmp:
        for rel in FILES:
            try:
                with urllib.request.urlopen(f"{RAW}/{rel}", timeout=30) as resp:
                    data = resp.read()
            except Exception as e:
                errors.append(f"{rel}: {type(e).__name__}")
                continue
            path = os.path.join(tmp, rel.replace("/", "_"))
            with open(path, "wb") as fh:
                fh.write(data)
            if rel.endswith(".py") and data.strip():
                try:
                    py_compile.compile(path, doraise=True, cfile=path + "c")
                except py_compile.PyCompileError as e:
                    errors.append(f"{rel}: syntax {e}")
                    continue
            staged[rel] = path

        if errors:
            await message.answer("❌ به‌روزرسانی انجام نشد (چیزی تغییر نکرد):\n"
                                 + "\n".join(errors[:6]))
            return

        for rel, path in staged.items():
            dest = os.path.join(install_dir, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copyfile(path, dest)

    service = os.path.basename(install_dir)
    await message.answer(f"✅ {len(staged)} فایل به‌روز شد.\n♻️ در حال ری‌استارت {service}…\n\n"
                         "چند ثانیه صبر کن بعد /diag بزن.")
    subprocess.Popen(["systemctl", "restart", service])


@router.message(Command("testtunnel"))
async def testtunnel(message: Message):
    """Connect to our own inbound as a real client, from this server.

    This is the one test the user's phone cannot substitute for: it proves
    whether a genuine Reality handshake succeeds against the inbound at all,
    independent of their carrier, app, or device.
    """
    if not _admin(message):
        return
    try:
        from utils.tunnel_test import run_probe
    except ImportError as e:
        await message.answer(
            f"❌ ماژول تست هنوز روی سرور نیست ({e}).\nیک بار دیگر /update بزن.")
        return

    await message.answer("⏳ در حال دانلود/اجرای Xray و تست اتصال واقعی به اینباند خودمان…")
    x = XUIClient()

    try:
        inbound = x.get_inbound()
        stream = inbound.get("streamSettings")
        stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
        reality = stream.get("realitySettings") or {}
        flow = x.client_flow()
    except (XUIError, ValueError) as e:
        await message.answer(f"❌ خواندن اینباند ناموفق: {e}")
        return

    email = f"nettest-{int(time.time())}"
    try:
        created = x.add_client(email=email, mb=50, hours=1)
    except XUIError as e:
        await message.answer(f"❌ ساخت کلاینت تستی ناموفق: {e}")
        return

    try:
        ok, ip_or_error, log_tail = run_probe(
            server_host=config.XUI_PUBLIC_HOST, server_port=inbound.get("port", 443),
            uuid=created["uuid"], reality=reality, flow=flow,
        )
    except Exception as e:
        await message.answer(f"❌ اجرای تست شکست خورد: {type(e).__name__}: {e}")
        ok, log_tail = False, ""
    finally:
        try:
            x.delete_client(inbound.get("id"), created["uuid"], email=email)
        except XUIError:
            pass

    if ok:
        msg = (f"✅ از همین سرور (فرانکفورت) به اینباند شما با موفقیت وصل شد.\n"
               f"IP دیده‌شده: {ip_or_error}\n\n"
               "یعنی سمت سرور کاملاً سالم است. اگر از گوشی همچنان وصل نمی‌شود، "
               "مشکل مسیر شبکه‌ی بین اپراتور تو در ترکیه و این سرور است — "
               "با وای‌فای یا اپراتور دیگر امتحان کن.")
    else:
        msg = f"❌ از این سرور هم وصل نشد ({ip_or_error}).\n\nبخشی از لاگ Xray:\n<pre>{log_tail[-3000:]}</pre>"
    await message.answer(msg, parse_mode="HTML")
PYEOF

cat > "$APP_DIR/bot/handlers/devmenu.py" << 'PYEOF'
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
PYEOF

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/keyboards.py" << 'PYEOF'
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config

MAIN_MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🛒 خرید سرویس"), KeyboardButton(text="📦 خرید عمده")],
        [KeyboardButton(text="🔄 تمدید سرویس"), KeyboardButton(text="🧪 تست")],
        [KeyboardButton(text="📶 وضعیت سرویس من"), KeyboardButton(text="♻️ دریافت دوباره لینک")],
        [KeyboardButton(text="🆘 پشتیبانی")],
    ],
    resize_keyboard=True,
)


def plans_keyboard(prefix: str = "buy") -> InlineKeyboardMarkup:
    rows = []
    for plan in config.PLANS:
        text = f"{plan['label']} — {plan['price']:,} تومان"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"{prefix}:{plan['key']}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_review_keyboard(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ تایید پرداخت", callback_data=f"approve:{order_id}"),
                InlineKeyboardButton(text="❌ رد", callback_data=f"reject:{order_id}"),
            ]
        ]
    )
PYEOF

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/main.py" << 'PYEOF'
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
import db
from handlers import admin, buy, ops, renew, start, status, trial


async def main():
    logging.basicConfig(level=logging.INFO)

    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is not set — copy .env.example to .env and fill it in.")
    if not config.ADMIN_IDS:
        logging.warning("ADMIN_IDS is empty — nobody will receive payment receipts to approve.")

    db.init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(renew.router)
    dp.include_router(trial.router)
    dp.include_router(status.router)
    dp.include_router(admin.router)
    dp.include_router(ops.router)

    # False, not True: /update and /restartxray restart this process often,
    # and a command sent in that few-second window must still be picked up
    # once polling resumes, not silently discarded.
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
PYEOF

cat > "$APP_DIR/bot/devbot_main.py" << 'PYEOF'
import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
import db
from handlers import devmenu, ops


async def main():
    logging.basicConfig(level=logging.INFO)

    if not config.DEV_BOT_TOKEN:
        raise SystemExit("DEV_BOT_TOKEN is not set — add it to .env and restart.")
    if not config.ADMIN_IDS:
        raise SystemExit("ADMIN_IDS is empty — this bot only answers admins, so nobody could use it.")

    db.init_db()

    bot = Bot(token=config.DEV_BOT_TOKEN)
    dp = Dispatcher()

    # devmenu first: its pending-action dispatcher only fires when an admin
    # has an open multi-step flow, so it never shadows ops.py's plain
    # /commands either way — but this keeps the menu's own crash reporter
    # first in line for its own buttons.
    dp.include_router(devmenu.router)
    dp.include_router(ops.router)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
PYEOF

mkdir -p "$APP_DIR/bot/utils"
cat > "$APP_DIR/bot/utils/__init__.py" << 'PYEOF'

PYEOF

mkdir -p "$APP_DIR/bot/utils"
cat > "$APP_DIR/bot/utils/pricing.py" << 'PYEOF'
import db


def unique_amount(base_price: int) -> int:
    """Append a small unique suffix to the price so a manual bank statement
    lookup can match a deposit to an order unambiguously (same trick as the
    reference bot: 60000 -> 60002).
    """
    for suffix in range(1, 100):
        candidate = base_price + suffix
        if not db.amount_in_use(candidate):
            return candidate
    # Extremely unlikely fallback if 99 orders for the exact same price are
    # all pending review simultaneously.
    return base_price + 1
PYEOF
cat > "$APP_DIR/bot/utils/delivery.py" << 'PYEOF'
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
PYEOF
cat > "$APP_DIR/bot/utils/x25519.py" << 'PYEOF'
"""X25519 public key derivation, to check a Reality keypair actually pairs.

Reality authenticates clients against the inbound's private key while the
link carries a public key the panel stores separately. If those two were ever
regenerated out of step, every client fails authentication and is handed to
the fallback site — a connection that looks healthy and carries nothing.

Verified against the RFC 7748 section 6.1 vectors.
"""
import base64

_P = 2**255 - 19
_A24 = 121665


def _clamp(private: bytes) -> int:
    k = bytearray(private)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return int.from_bytes(k, "little")


def scalarmult(private: bytes, u_int: int = 9) -> bytes:
    """Montgomery ladder; u defaults to the curve's base point."""
    k = _clamp(private)
    x1, x2, z2, x3, z3, swap = u_int, 1, 0, u_int, 1, 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3 = x3, x2
            z2, z3 = z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * ((da - cb) ** 2) % _P
        x2 = aa * bb % _P
        z2 = e * ((aa + _A24 * e) % _P) % _P
    if swap:
        x2, x3 = x3, x2
        z2, z3 = z3, z2
    return ((x2 * pow(z2, _P - 2, _P)) % _P).to_bytes(32, "little")


def _b64decode(value: str) -> bytes:
    """Xray writes keys base64url without padding."""
    value = value.strip().replace("-", "+").replace("_", "/")
    return base64.b64decode(value + "=" * (-len(value) % 4))


def public_from_private(private_b64: str) -> str:
    """Return the base64url public key matching an Xray Reality private key."""
    raw = _b64decode(private_b64)
    if len(raw) != 32:
        raise ValueError(f"private key is {len(raw)} bytes, expected 32")
    return base64.urlsafe_b64encode(scalarmult(raw)).decode().rstrip("=")
PYEOF
cat > "$APP_DIR/bot/utils/tunnel_test.py" << 'PYEOF'
"""Run a real Xray client against our own inbound, from the bot server itself.

This answers the one question nothing else can: does a genuine Reality
handshake succeed against this inbound at all, independent of the user's
phone, carrier, or app. If it works from here (Frankfurt) but not from the
user's device, the server is proven fine and the fault is on the path
between their carrier and the Iran server. If it fails here too, the debug
log says exactly why.
"""
import json
import os
import subprocess
import time
import urllib.request
import zipfile

XRAY_DIR = "/tmp/irannewvpn-xraytest"
XRAY_BIN = os.path.join(XRAY_DIR, "xray")
XRAY_URL = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"


def ensure_xray() -> str:
    """Download and unpack the Xray-core binary once; reuse it after that."""
    if os.path.isfile(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK):
        return XRAY_BIN
    os.makedirs(XRAY_DIR, exist_ok=True)
    zip_path = os.path.join(XRAY_DIR, "xray.zip")
    urllib.request.urlretrieve(XRAY_URL, zip_path)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extract("xray", XRAY_DIR)
    os.chmod(XRAY_BIN, 0o755)
    os.remove(zip_path)
    return XRAY_BIN


def build_client_config(socks_port: int, server_host: str, server_port: int,
                        uuid: str, reality: dict, flow: str) -> dict:
    settings = reality.get("settings") or {}
    names = reality.get("serverNames") or []
    short_ids = reality.get("shortIds") or []
    outbound_user = {"id": uuid, "encryption": "none"}
    if flow:
        outbound_user["flow"] = flow
    return {
        "log": {"loglevel": "debug"},
        "inbounds": [{"listen": "127.0.0.1", "port": socks_port, "protocol": "socks",
                      "settings": {"udp": False}}],
        "outbounds": [{
            "protocol": "vless",
            "settings": {"vnext": [{"address": server_host, "port": server_port,
                                    "users": [outbound_user]}]},
            "streamSettings": {
                "network": "tcp",
                "security": "reality",
                "realitySettings": {
                    "serverName": names[0] if names else "",
                    "fingerprint": settings.get("fingerprint", "chrome"),
                    "publicKey": settings.get("publicKey", ""),
                    "shortId": short_ids[0] if short_ids else "",
                    "spiderX": settings.get("spiderX", "/"),
                },
            },
        }],
    }


def run_probe(server_host: str, server_port: int, uuid: str, reality: dict,
             flow: str, socks_port: int = 19797, timeout: int = 20):
    """Returns (curl_ok, ip_or_error, log_tail)."""
    xray = ensure_xray()
    cfg_path = os.path.join(XRAY_DIR, "client.json")
    with open(cfg_path, "w") as fh:
        json.dump(build_client_config(socks_port, server_host, server_port, uuid, reality, flow), fh)

    log_path = os.path.join(XRAY_DIR, "run.log")
    with open(log_path, "w") as log_fh:
        proc = subprocess.Popen([xray, "run", "-c", cfg_path], stdout=log_fh, stderr=subprocess.STDOUT)
    try:
        time.sleep(2.5)  # let it bind the local socks listener
        try:
            result = subprocess.run(
                ["curl", "-s", "--max-time", str(timeout),
                 "--socks5-hostname", f"127.0.0.1:{socks_port}",
                 "https://api.ipify.org"],
                capture_output=True, text=True, timeout=timeout + 5,
            )
            curl_ok = result.returncode == 0 and bool(result.stdout.strip())
            ip_or_error = result.stdout.strip() if curl_ok else (
                result.stderr.strip() or f"curl exit {result.returncode}")
        except subprocess.TimeoutExpired:
            curl_ok, ip_or_error = False, "curl timed out"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    log_tail = ""
    if os.path.isfile(log_path):
        with open(log_path, errors="replace") as fh:
            lines = fh.readlines()
        log_tail = "".join(lines[-40:])

    return curl_ok, ip_or_error, log_tail
PYEOF

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/xui_client.py" << 'PYEOF'
"""Client for the 3x-ui v3 panel API.

Routes and payloads follow the panel's published OpenAPI description: clients
are their own resource under /panel/api/clients, not an operation on an
inbound. The panel generates the per-protocol secrets and renders the
subscription URLs, so neither is built here.

Authentication is the API token (Authorization: Bearer). Cookie login is only
attempted as a fallback for builds that lack token auth — this one answers
/login with 403 for any non-browser client.
"""
import json
import time

import requests

import config

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class XUIError(RuntimeError):
    pass


class XUIClient:
    def __init__(
        self,
        base_url: str = None,
        username: str = None,
        password: str = None,
        api_token: str = None,
    ):
        self.base_url = (base_url or config.XUI_BASE_URL).rstrip("/")
        self.username = username or config.XUI_USERNAME
        self.password = password or config.XUI_PASSWORD
        self.api_token = api_token if api_token is not None else config.XUI_API_TOKEN
        self.session = requests.Session()
        self.session.headers["User-Agent"] = BROWSER_UA
        self.session.headers["Accept"] = "application/json, text/plain, */*"
        if self.api_token:
            self.session.headers["Authorization"] = f"Bearer {self.api_token}"
        self._authed = bool(self.api_token)
        self._panel_settings = None
        self._flow = None

    def _login(self):
        if self._authed:
            return
        if not (self.username and self.password):
            raise XUIError("No XUI credentials: set XUI_API_TOKEN, or XUI_USERNAME/XUI_PASSWORD")
        try:
            self.session.get(self.base_url + "/", timeout=15)
            r = self.session.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                timeout=15,
            )
            r.raise_for_status()
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise XUIError(f"Cannot log in to panel at {self.base_url}: {e}") from e
        if not body.get("success"):
            raise XUIError(f"XUI login failed: {body}")
        self._authed = True

    def _request(self, method: str, path: str, **kwargs):
        self._login()
        url = f"{self.base_url}{path}"
        try:
            r = self.session.request(method, url, timeout=20, **kwargs)
            r.raise_for_status()
            body = r.json()
        except requests.RequestException as e:
            raise XUIError(f"{method} {path} failed: {e}") from e
        except ValueError as e:
            raise XUIError(f"{method} {path} returned non-JSON: {e}") from e
        if not body.get("success", False):
            raise XUIError(f"XUI API error on {path}: {body.get('msg') or body}")
        return body.get("obj")

    @staticmethod
    def _expiry_ms(days: int, hours: int = 0) -> int:
        if hours > 0:
            return int((time.time() + hours * 3600) * 1000)
        if days > 0:
            return int((time.time() + days * 86400) * 1000)
        return 0

    def add_client(self, email: str, gb: int = 0, days: int = 0, inbound_id: int = None,
                   hours: int = 0, mb: int = 0) -> dict:
        """Create a client and attach it to the configured inbound.

        Quota comes from `mb` when given (trials are sub-gigabyte), otherwise
        `gb`; 0 for both means unlimited. Pass either `days` or `hours` (hours
        wins); 0/0 means no expiry. The panel generates the UUID and subId.

        Returns dict with uuid, email, expiry_time (ms epoch), total_gb.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        expiry_ms = self._expiry_ms(days, hours)
        total_bytes = mb * 1024 * 1024 if mb > 0 else (gb * 1024 * 1024 * 1024 if gb > 0 else 0)
        client = {
            "email": email,
            "totalGB": total_bytes,
            "expiryTime": expiry_ms,
            "tgId": 0,
            "limitIp": 0,
            "limitHwid": 0,
            "enable": True,
        }
        flow = self.client_flow(inbound_id)
        if flow:
            client["flow"] = flow
        payload = {
            "client": client,
            "inboundIds": [int(inbound_id)],
        }
        self._request("POST", "/panel/api/clients/add", json=payload)
        created = self.get_client_traffic(email) or {}
        return {
            "uuid": created.get("uuid", ""),
            "email": email,
            "expiry_time": expiry_ms,
            "total_gb": gb,
        }

    def update_client(self, client_uuid: str, email: str, gb: int, days: int, inbound_id: int = None) -> dict:
        """Renew a client's quota and expiry (the 'renew service' flow)."""
        expiry_ms = self._expiry_ms(days)
        payload = {
            "email": email,
            "totalGB": 0 if gb <= 0 else gb * 1024 * 1024 * 1024,
            "expiryTime": expiry_ms,
            "enable": True,
        }
        flow = self.client_flow(inbound_id)
        if flow:
            payload["flow"] = flow
        self._request("POST", f"/panel/api/clients/update/{email}", json=payload)
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def delete_client(self, inbound_id: int, client_uuid: str, email: str = None):
        """Delete a client. The panel addresses clients by email, not UUID."""
        if not email:
            raise XUIError("delete_client needs the client's email on this panel version")
        self._request("POST", f"/panel/api/clients/del/{email}")

    def get_client_traffic(self, email: str) -> dict | None:
        try:
            return self._request("GET", f"/panel/api/clients/traffic/{email}")
        except XUIError:
            return None

    def get_inbound(self, inbound_id: int = None) -> dict:
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        return self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")

    def client_flow(self, inbound_id: int = None) -> str:
        """The XTLS flow this inbound's clients need, or "" when it takes none.

        VLESS over Reality (or TLS) on raw TCP is the one combination that
        wants xtls-rprx-vision; setting it anywhere else breaks the client.
        """
        if self._flow is None:
            self._flow = ""
            try:
                inbound = self.get_inbound(inbound_id)
                stream = inbound.get("streamSettings")
                stream = json.loads(stream) if isinstance(stream, str) else (stream or {})
                network = stream.get("network", "tcp")
                security = stream.get("security", "")
                if (inbound.get("protocol") == "vless"
                        and network in ("tcp", "raw")
                        and security in ("reality", "tls")):
                    self._flow = "xtls-rprx-vision"
            except (XUIError, ValueError):
                pass
        return self._flow

    def _settings(self) -> dict:
        if self._panel_settings is None:
            try:
                self._panel_settings = self._request("POST", "/panel/api/setting/all") or {}
            except XUIError:
                self._panel_settings = {}
        return self._panel_settings

    def get_sub_url(self, email: str) -> str:
        """Subscription URL for a client, or "" when the panel has none enabled.

        The subscription server is configured independently of the panel (own
        port, path and optional domain), so the address is read from the
        panel's settings rather than derived from the API URL.
        """
        settings = self._settings()
        if not settings:
            return ""
        enabled = settings.get("subEnable", settings.get("subenable"))
        if enabled in (False, "false", 0, "0"):
            return ""

        traffic = self.get_client_traffic(email) or {}
        sub_id = traffic.get("subId") or traffic.get("subid")
        if not sub_id:
            return ""

        explicit = settings.get("subURI") or settings.get("subUri") or settings.get("suburi")
        if explicit:
            return explicit.rstrip("/") + "/" + sub_id

        host = (settings.get("subDomain") or settings.get("subdomain")
                or config.XUI_PUBLIC_HOST
                or self.base_url.split("//", 1)[-1].split(":")[0].split("/")[0])
        port = settings.get("subPort") or settings.get("subport")
        path = settings.get("subPath") or settings.get("subpath") or "/sub/"
        scheme = "https" if (settings.get("subKeyFile") or settings.get("subCertFile")) else "http"

        netloc = f"{host}:{port}" if port and str(port) not in ("80", "443") else host
        return f"{scheme}://{netloc}{path if path.startswith('/') else '/' + path}{sub_id}"

    def build_vless_link(self, client_uuid: str, email: str, remark: str = "") -> str:
        """Return the client's connection URL as the panel renders it.

        The panel knows the inbound's advertised hosts, Reality keys and
        protocol, so its own link is authoritative — including for inbounds
        that are not Reality at all.
        """
        links = self._request("GET", f"/panel/api/clients/links/{email}") or []
        if not links:
            raise XUIError(f"panel returned no connection link for {email}")
        link = links[0]
        if remark:
            link = link.split("#", 1)[0] + "#" + remark
        return link
PYEOF

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/requirements.txt" << 'PYEOF'
aiogram>=3.4,<4
requests>=2.31
python-dotenv>=1.0
qrcode[pil]>=7.4
PYEOF

echo "==> Python venv + deps"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/bot/requirements.txt"

echo "==> Writing bot/.env"
cat > "$APP_DIR/bot/.env" << ENVEOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
SUPPORT_USERNAME=${SUPPORT_USERNAME:-@your_support}
BOT_NAME=${BOT_NAME:-VPN Store}
CARD_NUMBER=${CARD_NUMBER}
CARD_OWNER=${CARD_OWNER}
XUI_BASE_URL=${XUI_BASE_URL}
XUI_API_TOKEN=${XUI_API_TOKEN}
XUI_USERNAME=${XUI_USERNAME}
XUI_PASSWORD=${XUI_PASSWORD}
XUI_INBOUND_ID=${XUI_INBOUND_ID}
XUI_PUBLIC_HOST=${XUI_PUBLIC_HOST}
DB_PATH=${APP_DIR}/bot/bot.db
TRIAL_GB=${TRIAL_GB:-1}
TRIAL_HOURS=${TRIAL_HOURS:-24}
DEV_BOT_TOKEN=${DEV_BOT_TOKEN:-}
ENVEOF

echo "==> systemd service"
cat > /etc/systemd/system/hermes-vpn-bot.service << 'SERVICEEOF'
[Unit]
Description=Hermes VPN Telegram sales bot
After=network.target

[Service]
WorkingDirectory=/opt/hermes-vpn-bot/bot
ExecStart=/opt/hermes-vpn-bot/venv/bin/python /opt/hermes-vpn-bot/bot/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICEEOF

systemctl daemon-reload
systemctl enable --now hermes-vpn-bot

echo "==> systemd service (maintenance/developer bot)"
cat > /etc/systemd/system/hermes-vpn-bot-dev.service << 'SERVICEEOF'
[Unit]
Description=iranvpn maintenance/developer Telegram bot
After=network.target hermes-vpn-bot.service

[Service]
WorkingDirectory=/opt/hermes-vpn-bot/bot
ExecStart=/opt/hermes-vpn-bot/venv/bin/python /opt/hermes-vpn-bot/bot/devbot_main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
SERVICEEOF

if [ -n "${DEV_BOT_TOKEN:-}" ]; then
  systemctl enable --now hermes-vpn-bot-dev
else
  systemctl daemon-reload
  echo "  DEV_BOT_TOKEN not set — service installed but not started; set it in .env and 'systemctl enable --now hermes-vpn-bot-dev' when ready."
fi

sleep 2

cat <<SUMMARY

================================================================
Done. Bot: systemctl status hermes-vpn-bot   (logs: journalctl -u hermes-vpn-bot -f)

IMPORTANT — on the VPN server (Iran), allow THIS server's IP to reach
the panel port, instead of opening it to the whole internet:
  ufw allow from <this-server-public-ip> to any port <PANEL_PORT> proto tcp
================================================================
SUMMARY

systemctl status hermes-vpn-bot --no-pager || true

