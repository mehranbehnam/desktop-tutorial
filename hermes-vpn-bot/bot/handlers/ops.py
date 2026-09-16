"""Operator commands, so running the service never requires an SSH session.

The phone keeps dropping SSH; the bot does not. Everything here is admin-only
and answers in Telegram.
"""
import email.utils
import json
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
