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

HELP = (
    "🛠 دستورهای مدیریت:\n\n"
    "/diag — بررسی کامل سرور و پنل\n"
    "/clients — فهرست کلاینت‌ها و وضعیتشان\n"
    "/fixflow — اصلاح flow همه‌ی کلاینت‌های قدیمی\n"
    "/fixkeys — بازتولید کلید Reality وقتی جفت نیست\n"
    "/restartxray — ری‌استارت هسته‌ی Xray\n"
    "/update — دریافت آخرین نسخه‌ی کد و ری‌استارت\n"
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
    "bot/config.py", "bot/db.py", "bot/keyboards.py", "bot/main.py", "bot/xui_client.py",
    "bot/handlers/__init__.py", "bot/handlers/admin.py", "bot/handlers/buy.py",
    "bot/handlers/renew.py", "bot/handlers/start.py", "bot/handlers/status.py",
    "bot/handlers/trial.py", "bot/handlers/ops.py",
    "bot/utils/__init__.py", "bot/utils/pricing.py", "bot/utils/delivery.py",
    "bot/utils/x25519.py",
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

