"""Scheduled housekeeping so stale orders and expired accounts don't pile
up on the panel:

- An order stuck in "awaiting_review" (payment never confirmed, or an
  admin never got to it) for more than 24h is auto-rejected — its
  unique-amount slot would otherwise stay reserved forever and the
  "📤 سفارش‌های معطل" list would only ever grow.
- Any XUI client (real accounts and expired free-trial/test accounts
  alike) whose expiry time has already passed gets deleted from the
  panel — same thing "🗑 حذف انبوه (منقضی‌شده‌ها)" does by hand, just run
  automatically so nobody has to remember to tap it.

Runs on a timer in the dev bot process (see devbot_main.py) and pings the
admins with a one-line summary only when it actually cleaned something up.
"""
import asyncio
import json
import logging
import time

from aiogram import Bot

import config
import db
from xui_client import XUIClient, XUIError

log = logging.getLogger(__name__)

PENDING_TIMEOUT_SECONDS = 24 * 3600
CHECK_INTERVAL_SECONDS = 3600


async def _expire_stale_orders(bot: Bot) -> list[int]:
    cutoff = int(time.time()) - PENDING_TIMEOUT_SECONDS
    expired_ids = []
    for order in db.pending_orders(limit=1000):
        if not order["created_at"] or order["created_at"] >= cutoff:
            continue
        db.set_order_status(order["id"], "rejected")
        expired_ids.append(order["id"])
        try:
            await bot.send_message(
                order["tg_id"],
                "⏳ سفارشت به‌خاطر عدم تایید طی ۲۴ ساعت لغو شد. اگر واریز کردی و "
                "تاییدش نشده، با پشتیبانی تماس بگیر.",
            )
        except Exception:
            log.exception("cleanup: failed to notify tg_id %s about expired order %s",
                          order["tg_id"], order["id"])
    return expired_ids


def _list_xui_clients(x: XUIClient) -> list[dict]:
    inbound = x.get_inbound()
    settings = inbound.get("settings")
    settings = json.loads(settings) if isinstance(settings, str) else (settings or {})
    return settings.get("clients") or []


async def _delete_expired_clients() -> list[str]:
    x = XUIClient()
    try:
        clients = _list_xui_clients(x)
    except (XUIError, ValueError):
        log.exception("cleanup: failed to read client list")
        return []
    now_ms = time.time() * 1000
    deleted = []
    for c in clients:
        email = c.get("email")
        if not email:
            continue
        t = x.get_client_traffic(email) or {}
        exp = t.get("expiryTime", 0)
        if not exp or exp >= now_ms:
            continue  # no expiry, or not expired yet
        try:
            x.delete_client(inbound_id=config.XUI_INBOUND_ID, client_uuid="", email=email)
            deleted.append(email)
        except XUIError:
            log.exception("cleanup: failed to delete expired client %s", email)
    return deleted


async def run_once(bot: Bot):
    expired_orders = await _expire_stale_orders(bot)
    deleted_clients = await _delete_expired_clients()
    if not expired_orders and not deleted_clients:
        return

    lines = ["🧹 پاکسازی خودکار انجام شد:"]
    if expired_orders:
        ids = ", ".join(f"#{i}" for i in expired_orders[:10])
        more = " …" if len(expired_orders) > 10 else ""
        lines.append(f"— {len(expired_orders)} سفارش معطل‌مانده (بیش از ۲۴ ساعت) لغو شد: {ids}{more}")
    if deleted_clients:
        names = ", ".join(deleted_clients[:10])
        more = " …" if len(deleted_clients) > 10 else ""
        lines.append(f"— {len(deleted_clients)} اکانت منقضی‌شده حذف شد: {names}{more}")
    text = "\n".join(lines)

    for admin_id in config.ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            log.exception("cleanup: failed to notify admin %s", admin_id)


async def cleanup_loop(bot: Bot):
    while True:
        try:
            await run_once(bot)
        except Exception:
            log.exception("cleanup loop iteration failed")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
