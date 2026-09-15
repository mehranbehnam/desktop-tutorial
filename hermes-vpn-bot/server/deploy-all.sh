#!/usr/bin/env bash
# Fully automated deploy: installs 3x-ui, reads its auto-generated panel
# credentials + API token, writes the bot code, creates a VLESS+Reality
# inbound, configures .env, and starts the bot as a systemd service.
# Run as root on the VPS.
#
# Usage:
#   BOT_TOKEN=... ADMIN_IDS=... CARD_NUMBER=... CARD_OWNER=... bash deploy-all.sh
#
# Optional overrides: REALITY_SNI, INBOUND_PORT.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run as root" >&2; exit 1; fi

: "${BOT_TOKEN:?Set BOT_TOKEN=...}"
: "${ADMIN_IDS:?Set ADMIN_IDS=your_numeric_telegram_id}"
: "${CARD_NUMBER:?Set CARD_NUMBER=...}"
: "${CARD_OWNER:?Set CARD_OWNER=...}"

REALITY_SNI=${REALITY_SNI:-www.microsoft.com}
INBOUND_PORT=${INBOUND_PORT:-443}
APP_DIR=/opt/hermes-vpn-bot

echo "==> System packages, swap, firewall"
if command -v apt-get >/dev/null 2>&1; then
  PKG_MGR=apt
  apt-get update -y
  apt-get install -y curl socat ufw python3-venv python3-pip openssl
elif command -v dnf >/dev/null 2>&1; then
  PKG_MGR=dnf
  dnf install -y curl socat python3 python3-pip openssl firewalld
  systemctl enable --now firewalld
elif command -v yum >/dev/null 2>&1; then
  PKG_MGR=yum
  yum install -y curl socat python3 python3-pip openssl firewalld
  systemctl enable --now firewalld
else
  echo "No supported package manager found (apt-get/dnf/yum)." >&2
  exit 1
fi

# Opens a TCP port on whichever local firewall is present. On a cloud VM this
# is only half the story — the provider's own network-level firewall (e.g.
# Oracle's Security List / AWS Security Group) gates traffic before it even
# reaches this box, and has to be opened separately in that provider's console.
fw_allow_port() {
  local port="$1"
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${port}/tcp"
  elif command -v firewall-cmd >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="${port}/tcp"
    firewall-cmd --reload
  fi
}

if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

if [[ "$PKG_MGR" == apt ]]; then
  ufw allow OpenSSH
fi
fw_allow_port "$INBOUND_PORT"
if command -v ufw >/dev/null 2>&1; then
  ufw --force enable
fi

echo "==> Installing 3x-ui"
# The installer auto-generates a strong random username/password/port/base-path
# plus an API token, and writes them to /etc/x-ui/install-result.env — newer
# panel versions require that Bearer token for programmatic API access (the
# cookie-session /login endpoint returns a bare 403 for non-browser clients).
bash <(curl -Ls https://raw.githubusercontent.com/MHSanaei/3x-ui/master/install.sh) <<< $'\n'

echo "==> Reading auto-generated panel credentials"
RESULT_FILE=/etc/x-ui/install-result.env
if [[ ! -f "$RESULT_FILE" ]]; then
  echo "Could not find $RESULT_FILE — install may have failed, check 'x-ui status'." >&2
  exit 1
fi
get_val() {
  local line val
  line=$(grep -iE "^${1}[[:space:]]*=" "$RESULT_FILE" | tail -1)
  val="${line#*=}"
  val="${val%$'\r'}"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  printf '%s' "$val"
}
PANEL_USERNAME=$(get_val username)
PANEL_PASSWORD=$(get_val password)
PANEL_PORT=$(get_val port)
WEB_BASE_PATH=$(get_val webBasePath)
API_TOKEN=$(get_val apiToken)
[[ -z "$API_TOKEN" ]] && API_TOKEN=$(get_val api_token)
[[ -z "$API_TOKEN" ]] && API_TOKEN=$(get_val token)
: "${PANEL_USERNAME:?Could not read panel username from $RESULT_FILE}"
: "${PANEL_PASSWORD:?Could not read panel password from $RESULT_FILE}"
: "${PANEL_PORT:?Could not read panel port from $RESULT_FILE}"
: "${API_TOKEN:?Could not read API token from $RESULT_FILE}"

XUI_BASE_URL="http://127.0.0.1:${PANEL_PORT}"
[[ -n "${WEB_BASE_PATH:-}" ]] && XUI_BASE_URL="${XUI_BASE_URL}/${WEB_BASE_PATH}"
SERVER_IP=$(curl -s https://ifconfig.me || hostname -I | awk '{print $1}')

fw_allow_port "$PANEL_PORT"

echo "==> Waiting for the panel to accept connections on port ${PANEL_PORT}"
for i in $(seq 1 20); do
  curl -s --max-time 1 -o /dev/null "http://127.0.0.1:${PANEL_PORT}/" && break
  sleep 1
done

echo "==> Writing bot source to $APP_DIR"
mkdir -p "$APP_DIR/bot" "$APP_DIR/server"

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

TRIAL_GB = int(os.getenv("TRIAL_GB", "1"))
TRIAL_HOURS = int(os.getenv("TRIAL_HOURS", "24"))

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

    await bot.send_message(
        order["tg_id"],
        "✅ پرداخت تایید شد و سرویس شما فعال شد!\n\n"
        f"لینک اتصال:\n`{link}`\n\n"
        "این لینک رو در اپلیکیشن v2rayNG / NekoBox / Streisand وارد کن.",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU,
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
PYEOF

mkdir -p "$APP_DIR/bot/handlers"
cat > "$APP_DIR/bot/handlers/trial.py" << 'PYEOF'
import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import Message

import config
import db
from xui_client import XUIClient

router = Router()
log = logging.getLogger(__name__)


@router.message(F.text == "🧪 تست")
async def trial(message: Message, bot: Bot):
    tg_id = message.from_user.id
    if db.has_used_trial(tg_id):
        await message.answer("شما قبلاً از سرویس تست استفاده کردی. برای ادامه یکی از پلن‌ها رو بخر.")
        return

    email = f"trial{tg_id}-{int(time.time())}"
    try:
        xui = XUIClient()
        client = xui.add_client(email=email, gb=config.TRIAL_GB, hours=config.TRIAL_HOURS)
        link = xui.build_vless_link(client["uuid"], email)
    except Exception as e:
        log.exception("trial provisioning failed for %s", tg_id)
        detail = f"\n\n`{type(e).__name__}: {e}`" if tg_id in config.ADMIN_IDS else ""
        await message.answer(
            "خطا در ساخت اکانت تست، لطفاً بعداً دوباره امتحان کن یا با پشتیبانی تماس بگیر." + detail,
            parse_mode="Markdown" if detail else None,
        )
        return

    db.save_client(email, tg_id, client["uuid"], config.TRIAL_GB, client["expiry_time"])
    db.mark_trial_used(tg_id)

    await message.answer(
        f"🧪 اکانت تست ساخته شد ({config.TRIAL_GB} گیگ / {config.TRIAL_HOURS} ساعت):\n\n"
        f"`{link}`",
        parse_mode="Markdown",
    )
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
from handlers import admin, buy, renew, start, status, trial


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

    await bot.delete_webhook(drop_pending_updates=True)
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

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/xui_client.py" << 'PYEOF'
"""Thin wrapper around the x-ui / 3x-ui panel REST API.

Route layout differs between panel builds: some expose everything under
/panel/api/inbounds/*, others only implement reads there and keep the
mutating calls on the web-UI routes under /panel/inbound/*. Each call below
therefore tries the known candidates in order and keeps the one that answers.

The panel also rejects requests without a browser-like User-Agent, and
mutating calls need a real login cookie even when an API token is present.
"""
import json
import time
import uuid

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
        self._authed = False

    def _login(self):
        """Establish a cookie session. Mutating routes need it even with a token."""
        if not (self.username and self.password):
            if not self.api_token:
                raise XUIError("No XUI credentials: set XUI_USERNAME/XUI_PASSWORD or XUI_API_TOKEN")
            self._authed = True
            return

        try:
            # Touch the root page first so the panel hands out its initial cookie.
            self.session.get(self.base_url + "/", timeout=15)
            r = self.session.post(
                f"{self.base_url}/login",
                data={"username": self.username, "password": self.password},
                timeout=15,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise XUIError(f"Cannot reach panel at {self.base_url}: {e}") from e
        try:
            body = r.json()
        except ValueError:
            raise XUIError(f"XUI login returned non-JSON (HTTP {r.status_code})")
        if not body.get("success"):
            raise XUIError(f"XUI login failed: {body}")
        self._authed = True

    def _try_paths(self, method: str, paths: list[str], **kwargs):
        """Call the first candidate path the panel actually implements.

        A 404 means "wrong route for this build" — move on to the next one.
        """
        if not self._authed:
            self._login()

        last_error = None
        for path in paths:
            try:
                r = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
                if r.status_code in (401, 403):
                    self._login()
                    r = self.session.request(method, f"{self.base_url}{path}", timeout=20, **kwargs)
                if r.status_code == 404:
                    last_error = f"{path} -> 404"
                    continue
                r.raise_for_status()
            except requests.RequestException as e:
                last_error = f"{path} -> {e}"
                continue
            try:
                body = r.json()
            except ValueError:
                last_error = f"{path} -> non-JSON response"
                continue
            if not body.get("success", False):
                raise XUIError(f"XUI API error on {path}: {body}")
            return body.get("obj")

        raise XUIError(f"No working route among {paths} ({last_error})")

    @staticmethod
    def _build_client(client_uuid: str, email: str, gb: int, expiry_ms: int) -> dict:
        return {
            "id": client_uuid,
            "email": email,
            "limitIp": 0,
            "totalGB": 0 if gb <= 0 else gb * 1024 * 1024 * 1024,
            "expiryTime": expiry_ms,
            "enable": True,
            "tgId": "",
            "subId": uuid.uuid4().hex[:16],
            "flow": "xtls-rprx-vision",
        }

    def add_client(self, email: str, gb: int, days: int = 0, inbound_id: int = None, hours: int = 0) -> dict:
        """Create a VLESS client inside the configured inbound.

        Pass either `days` or `hours` (hours wins if both are given, e.g. for
        short trial accounts). 0/0 means no expiry.

        Returns dict with uuid, email, expiry_time (ms epoch), total_gb.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        client_uuid = str(uuid.uuid4())
        if hours > 0:
            expiry_ms = int((time.time() + hours * 3600) * 1000)
        elif days > 0:
            expiry_ms = int((time.time() + days * 86400) * 1000)
        else:
            expiry_ms = 0

        client = self._build_client(client_uuid, email, gb, expiry_ms)
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        self._try_paths(
            "POST",
            ["/panel/inbound/addClient", "/panel/api/inbounds/addClient"],
            data=payload,
        )
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def update_client(self, client_uuid: str, email: str, gb: int, days: int, inbound_id: int = None) -> dict:
        """Renew/replace a client's quota and expiry (used for the 'renew service' flow)."""
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        expiry_ms = 0 if days <= 0 else int((time.time() + days * 86400) * 1000)

        client = self._build_client(client_uuid, email, gb, expiry_ms)
        payload = {"id": inbound_id, "settings": json.dumps({"clients": [client]})}
        self._try_paths(
            "POST",
            [
                f"/panel/inbound/updateClient/{client_uuid}",
                f"/panel/api/inbounds/updateClient/{client_uuid}",
            ],
            data=payload,
        )
        return {"uuid": client_uuid, "email": email, "expiry_time": expiry_ms, "total_gb": gb}

    def delete_client(self, inbound_id: int, client_uuid: str):
        self._try_paths(
            "POST",
            [
                f"/panel/inbound/{inbound_id}/delClient/{client_uuid}",
                f"/panel/api/inbounds/{inbound_id}/delClient/{client_uuid}",
            ],
        )

    def get_client_traffic(self, email: str) -> dict | None:
        return self._try_paths(
            "GET",
            [
                f"/panel/api/inbounds/getClientTraffics/{email}",
                f"/panel/inbound/getClientTraffics/{email}",
            ],
        )

    def get_inbound(self, inbound_id: int = None) -> dict:
        """Fetch one inbound, falling back to filtering the full list.

        /panel/api/inbounds/list is the one route confirmed present on every
        build we've seen, so it is the reliable fallback.
        """
        inbound_id = inbound_id or config.XUI_INBOUND_ID
        try:
            return self._try_paths(
                "GET",
                [f"/panel/api/inbounds/get/{inbound_id}", f"/panel/inbound/get/{inbound_id}"],
            )
        except XUIError:
            inbounds = self._try_paths("GET", ["/panel/api/inbounds/list"]) or []
            for inbound in inbounds:
                if inbound.get("id") == inbound_id:
                    return inbound
            raise XUIError(f"Inbound {inbound_id} not found in panel inbound list")

    def build_vless_link(self, client_uuid: str, email: str, remark: str = "") -> str:
        """Builds a vless:// link from the inbound's Reality stream settings.

        Good enough for manual copy/paste into v2rayNG / NekoBox / Streisand etc.
        """
        inbound = self.get_inbound()
        try:
            stream = json.loads(inbound["streamSettings"])
            reality = stream["realitySettings"]
            port = inbound["port"]
        except (KeyError, ValueError, TypeError) as e:
            raise XUIError(f"Inbound {inbound.get('id')} is not a Reality inbound: {e}") from e

        # The panel API is reached over localhost/LAN for security, but the
        # client link must point at the server's public IP/domain.
        host = config.XUI_PUBLIC_HOST or self.base_url.split("//", 1)[-1].split(":")[0].split("/")[0]

        try:
            params = {
                "type": stream.get("network", "tcp"),
                "security": "reality",
                "pbk": reality["settings"]["publicKey"],
                "fp": reality["settings"].get("fingerprint", "chrome"),
                "sni": reality["serverNames"][0],
                "sid": reality["shortIds"][0],
                "spx": reality["settings"].get("spiderX", "/"),
                "flow": "xtls-rprx-vision",
            }
        except (KeyError, IndexError) as e:
            raise XUIError(f"Reality settings incomplete on inbound: missing {e}") from e
        query = "&".join(f"{k}={v}" for k, v in params.items())
        tag = remark or email
        return f"vless://{client_uuid}@{host}:{port}?{query}#{tag}"
PYEOF

mkdir -p "$APP_DIR/bot"
cat > "$APP_DIR/bot/requirements.txt" << 'PYEOF'
aiogram>=3.4,<4
requests>=2.31
python-dotenv>=1.0
PYEOF

mkdir -p "$APP_DIR/server"
cat > "$APP_DIR/server/setup_inbound.py" << 'PYEOF'
#!/usr/bin/env python3
"""
One-time helper: connects to a freshly-installed 3x-ui panel and creates a
VLESS + Reality inbound (no TLS certs to manage, good default for a small
VPS). Prints the values you need to put in bot/.env when it's done.

Auth: newer 3x-ui versions print an API Token at install time (see
/etc/x-ui/install-result.env) and require it for programmatic access —
the cookie-session /login endpoint rejects non-browser clients with a
plain 403. Pass that token with --api-token.

Usage:
    pip install requests
    python3 setup_inbound.py \
        --url http://127.0.0.1:PANEL_PORT/WEB_BASE_PATH \
        --api-token YOUR_API_TOKEN \
        --port 443 --sni www.microsoft.com
"""
import argparse
import glob
import json
import shutil
import subprocess
import sys
import uuid

import requests


def build_session(api_token: str) -> requests.Session:
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {api_token}"
    return session


def find_xray_binary() -> str:
    """Locate the xray-core binary x-ui manages, rather than guessing the
    panel's API route for key generation (that route's path has changed
    between panel versions and isn't worth chasing)."""
    candidates = [
        "/usr/local/x-ui/bin/xray-linux-amd64",
        "/usr/local/x-ui/bin/xray-linux-arm64",
        "/usr/local/x-ui/bin/xray-linux-arm64-v8a",
        "/usr/local/x-ui/xray-linux-amd64",
    ]
    candidates += glob.glob("/usr/local/x-ui/bin/xray-linux-*")
    for c in candidates:
        if shutil.which(c):
            return c
    found = shutil.which("xray")
    if found:
        return found
    raise RuntimeError(
        "Could not find the xray binary (looked under /usr/local/x-ui/bin and PATH). "
        "Run 'find / -name \"xray-linux-*\" 2>/dev/null' on the server to locate it."
    )


def generate_x25519_keypair() -> dict:
    xray_bin = find_xray_binary()
    result = subprocess.run([xray_bin, "x25519"], capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(f"'{xray_bin} x25519' failed:\n{result.stderr}")

    private_key = public_key = None
    for line in result.stdout.splitlines():
        line = line.strip()
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        label = label.strip().lower()
        value = value.strip()
        # Label wording varies across xray-core versions/builds, e.g.
        # "PrivateKey:" vs "Private key:", and the public key has shown up
        # as "PublicKey:" or "Password (PublicKey):" — match by substring.
        if "private" in label:
            private_key = value
        elif "public" in label or "password" in label:
            public_key = value

    if not private_key or not public_key:
        raise RuntimeError(f"Could not parse '{xray_bin} x25519' output:\n{result.stdout}")
    return {"privateKey": private_key, "publicKey": public_key}


def create_inbound(session: requests.Session, base_url: str, port: int, remark: str, sni: str, keypair: dict) -> dict:
    short_id = uuid.uuid4().hex[:8]

    settings = {
        "clients": [],
        "decryption": "none",
        "fallbacks": [],
    }

    stream_settings = {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
            "show": False,
            "dest": f"{sni}:443",
            "xver": 0,
            "serverNames": [sni],
            "privateKey": keypair["privateKey"],
            "publicKey": keypair["publicKey"],
            "shortIds": [short_id],
            "settings": {
                "publicKey": keypair["publicKey"],
                "fingerprint": "chrome",
                "serverName": sni,
                "spiderX": "/",
            },
        },
    }

    sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic"]}

    payload = {
        "up": 0,
        "down": 0,
        "total": 0,
        "remark": remark,
        "enable": True,
        "expiryTime": 0,
        "listen": "",
        "port": port,
        "protocol": "vless",
        "settings": json.dumps(settings),
        "streamSettings": json.dumps(stream_settings),
        "sniffing": json.dumps(sniffing),
    }

    r = session.post(f"{base_url}/panel/api/inbounds/add", data=payload, timeout=15)
    r.raise_for_status()
    body = r.json()
    if not body.get("success", False):
        raise RuntimeError(f"Could not create inbound: {body}")
    return body["obj"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="e.g. http://127.0.0.1:PANEL_PORT/WEB_BASE_PATH")
    ap.add_argument("--api-token", required=True, help="from /etc/x-ui/install-result.env")
    ap.add_argument("--public-host", default="", help="public IP/domain clients connect to (for reference only)")
    ap.add_argument("--port", type=int, default=443, help="Public port clients connect to")
    ap.add_argument("--remark", default="main")
    ap.add_argument("--sni", default="www.microsoft.com", help="Reality masking domain (a real, reachable HTTPS site)")
    args = ap.parse_args()

    base_url = args.url.rstrip("/")
    session = build_session(args.api_token)

    print("Generating Reality keypair (via local xray binary)...")
    keypair = generate_x25519_keypair()

    print("Creating inbound...")
    inbound = create_inbound(session, base_url, args.port, args.remark, args.sni, keypair)

    print("\n=== Done. Put these in bot/.env ===")
    print(f"XUI_BASE_URL={base_url}")
    print(f"XUI_API_TOKEN={args.api_token}")
    print(f"XUI_INBOUND_ID={inbound['id']}")
    if args.public_host:
        print(f"XUI_PUBLIC_HOST={args.public_host}")
    print("\n(The bot creates/deletes clients inside this inbound automatically via the panel API.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF

echo "==> Python venv + deps"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/bot/requirements.txt"

echo "==> Creating VLESS+Reality inbound"
INBOUND_OUT=$("$APP_DIR/venv/bin/python" "$APP_DIR/server/setup_inbound.py" \
  --url "$XUI_BASE_URL" --api-token "$API_TOKEN" --public-host "$SERVER_IP" \
  --port "$INBOUND_PORT" --sni "$REALITY_SNI")
echo "$INBOUND_OUT"
INBOUND_ID=$(echo "$INBOUND_OUT" | grep XUI_INBOUND_ID | cut -d= -f2)

echo "==> Writing bot/.env"
cat > "$APP_DIR/bot/.env" << ENVEOF
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}
SUPPORT_USERNAME=${SUPPORT_USERNAME:-@your_support}
BOT_NAME=${BOT_NAME:-VPN Store}
CARD_NUMBER=${CARD_NUMBER}
CARD_OWNER=${CARD_OWNER}
XUI_BASE_URL=${XUI_BASE_URL}
XUI_API_TOKEN=${API_TOKEN}
XUI_USERNAME=${PANEL_USERNAME}
XUI_PASSWORD=${PANEL_PASSWORD}
XUI_INBOUND_ID=${INBOUND_ID}
XUI_PUBLIC_HOST=${SERVER_IP}
DB_PATH=${APP_DIR}/bot/bot.db
TRIAL_GB=${TRIAL_GB:-1}
TRIAL_HOURS=${TRIAL_HOURS:-24}
ENVEOF

echo "==> systemd service"
cat > /etc/systemd/system/hermes-vpn-bot.service << 'SERVICEEOF'
[Unit]
Description=Hermes VPN Telegram sales bot
After=network.target x-ui.service

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
sleep 2

cat <<SUMMARY

================================================================
Done.
Panel:   http://${SERVER_IP}:${PANEL_PORT}${WEB_BASE_PATH:+/${WEB_BASE_PATH}}  user=${PANEL_USERNAME} pass=${PANEL_PASSWORD}
Bot:     systemctl status hermes-vpn-bot   (logs: journalctl -u hermes-vpn-bot -f)
Reality inbound port: ${INBOUND_PORT}, SNI: ${REALITY_SNI}

If this box is on a cloud provider (Oracle/AWS/GCP/...), its own network
firewall (Security List / Security Group) still needs a rule allowing
TCP ${INBOUND_PORT} (and ${PANEL_PORT} if you want the panel reachable from
outside) inbound from 0.0.0.0/0 — the local ufw/firewalld rules above only
cover the OS, not that layer.
================================================================
SUMMARY

systemctl status hermes-vpn-bot --no-pager || true

