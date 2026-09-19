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
    "/liveconfig — مقایسه‌ی کانفیگ واقعیِ در حال اجرای Xray با چیزی که پنل نشون می‌ده\n"
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


@router.message(Command("liveconfig"))
async def live_config(message: Message):
    """What Xray is *actually* running, straight from getConfigJson — not
    what the panel's inbound record claims. /diag only checks that the
    panel's own stored keypair is self-consistent; it can't tell you
    whether the panel ever actually pushed that config into the running
    Xray process. When every client fails identically regardless of
    domain, key freshness, or a plain restart, that gap is the remaining
    suspect.
    """
    if not _admin(message):
        return
    x = XUIClient()
    try:
        cfg = x._request("GET", "/panel/api/server/getConfigJson")
    except XUIError as e:
        await message.answer(f"❌ خطا در گرفتن کانفیگ زنده: {e}")
        return

    try:
        want_port = x.get_inbound().get("port")
    except (XUIError, ValueError):
        want_port = None

    inbounds = (cfg or {}).get("inbounds") or []
    lines = [f"تعداد inbound در کانفیگ زنده‌ی Xray: {len(inbounds)}"]
    for ib in inbounds:
        sec = ((ib.get("streamSettings") or {}).get("security")) or "-"
        lines.append(f"   • tag={ib.get('tag')} port={ib.get('port')} "
                     f"listen={ib.get('listen') or '(همه)'} protocol={ib.get('protocol')} security={sec}")

    matched = False
    for ib in inbounds:
        port = ib.get("port")
        if want_port and port != want_port:
            continue
        matched = True
        stream = ib.get("streamSettings") or {}
        reality = stream.get("realitySettings") or {}
        priv = reality.get("privateKey", "")
        dest = reality.get("dest", "")
        short_ids = reality.get("shortIds", [])
        settings = ib.get("settings") or {}
        clients = settings.get("clients") or []
        lines.append(f"پورت {port}: dest={dest}")
        lines.append(f"   shortIds در کانفیگ زنده: {short_ids}")
        lines.append(f"   تعداد کلاینت در کانفیگ زنده: {len(clients)}")
        if priv:
            try:
                derived = public_from_private(priv)
                lines.append(f"   کلید عمومی مشتق‌شده از کلید *زنده*: {derived}")
            except ValueError as e:
                lines.append(f"   خطای مشتق کردن کلید: {e}")
        else:
            lines.append("   کلید خصوصی در کانفیگ زنده خالیه")
    if not matched:
        lines.append(f"⚠️ هیچ inbound-ی با پورت {want_port} تو کانفیگ زنده پیدا نشد.")

    await message.answer("🔬 کانفیگ زنده‌ی Xray (از getConfigJson):\n\n" + "\n".join(lines))


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


# raw.githubusercontent.com sits behind a CDN that turned out to cache
# stale content for much longer than a query-string cache-buster could
# reliably defeat (confirmed: a fix one commit behind another, in the same
# file, downloaded correctly while the newer one silently didn't). The
# Contents API isn't behind that CDN at all — this pays for that certainty
# with GitHub's unauthenticated rate limit (60/hour), which is fine for how
# often /update actually runs.
API_REPO = "https://api.github.com/repos/mehranbehnam/desktop-tutorial/contents/hermes-vpn-bot"
API_REF = "claude/iran-vpn-turkey-d2hbvg"
FILES = [
    "bot/config.py", "bot/db.py", "bot/keyboards.py", "bot/main.py", "bot/devbot_main.py",
    "bot/xui_client.py",
    "bot/handlers/__init__.py", "bot/handlers/admin.py", "bot/handlers/buy.py",
    "bot/handlers/renew.py", "bot/handlers/start.py", "bot/handlers/status.py",
    "bot/handlers/trial.py", "bot/handlers/ops.py", "bot/handlers/devmenu.py",
    "bot/utils/__init__.py", "bot/utils/pricing.py", "bot/utils/delivery.py",
    "bot/utils/x25519.py", "bot/utils/tunnel_test.py", "bot/utils/iran_ssh.py",
    "bot/utils/cloudflare.py",
    "bot/requirements.txt",
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
    import urllib.error
    import urllib.request

    bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    install_dir = os.path.dirname(bot_dir)
    await message.answer("⏳ در حال دریافت آخرین نسخه…")

    staged, errors = {}, []
    headers = {"Accept": "application/vnd.github.raw", "User-Agent": "irannewvpn-bot-update"}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    with tempfile.TemporaryDirectory() as tmp:
        for rel in FILES:
            req = urllib.request.Request(f"{API_REPO}/{rel}?ref={API_REF}", headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = resp.read()
            except urllib.error.HTTPError as e:
                detail = f"HTTP {e.code}"
                if e.code == 403 and "rate limit" in e.read().decode(errors="replace").lower():
                    detail += " (rate limit — بدون GITHUB_TOKEN فقط ۶۰ درخواست/ساعت مجازه)"
                errors.append(f"{rel}: {detail}")
                continue
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

    # A new dependency (like paramiko) is useless if it's never installed —
    # this used to only happen via a full setup_iran_vpn.sh re-run.
    pip = os.path.join(install_dir, "venv", "bin", "pip")
    if "bot/requirements.txt" in staged and os.path.isfile(pip):
        subprocess.run([pip, "install", "-q", "-r", os.path.join(install_dir, "bot", "requirements.txt")],
                       capture_output=True, timeout=120)

    # Restart both services: this code is shared by the sales bot and the
    # developer bot, and whichever one is running it needs the new files
    # loaded too. The developer service may not exist yet on a first-ever
    # /update (before setup_iran_vpn.sh has created it) — that failure is
    # harmless and silent.
    service = os.path.basename(install_dir)
    await message.answer(f"✅ {len(staged)} فایل به‌روز شد.\n♻️ در حال ری‌استارت سرویس‌ها…\n\n"
                         "چند ثانیه صبر کن بعد /diag بزن.")
    subprocess.Popen(["systemctl", "restart", service])
    subprocess.Popen(["systemctl", "restart", f"{service}-dev"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
