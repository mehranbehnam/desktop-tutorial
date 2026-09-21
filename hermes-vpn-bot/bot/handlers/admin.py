import logging
import os
import re
import subprocess
import time

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    Message,
)

import config
import db
from handlers.buy import provision_order

router = Router()
log = logging.getLogger(__name__)
_PID = os.getpid()
_LOADED_AT = time.time()


def _admin(message: Message) -> bool:
    return message.from_user.id in config.ADMIN_IDS


@router.message(Command("diagcmds"))
async def diag_commands(message: Message, bot: Bot):
    """Temporary diagnostic for the "/report keeps showing up no matter
    what" mystery — not a real feature, delete once that's resolved.

    Reports (1) whether more than one main.py process is actually
    running (a stray one outside systemd would keep answering with
    whatever command list IT set, regardless of what this process's own
    startup code does) and (2) the command list Telegram is really
    serving right now, straight from getMyCommands, for every
    scope/language combination this bot could plausibly have set one
    under — so nothing is guessed anymore.
    """
    if not _admin(message):
        return

    age = time.time() - _LOADED_AT
    lines = [f"PID این پردازش: {_PID}", f"{age:.0f} ثانیه پیش بالا اومده"]
    try:
        out = subprocess.run(["pgrep", "-af", "bot/main.py"], capture_output=True, text=True, timeout=5).stdout

        def _is_python_proc(line: str) -> bool:
            parts = line.split(None, 1)
            if len(parts) < 2:
                return False
            argv0 = parts[1].split()[0] if parts[1].split() else ""
            return "python" in os.path.basename(argv0)

        procs = [ln for ln in out.splitlines() if ln.strip() and _is_python_proc(ln)]
        lines.append(f"\nتعداد پردازش‌های main.py رو این سرور: {len(procs)}")
        lines.extend(procs)
    except Exception as e:
        lines.append(f"pgrep ناموفق: {e}")

    lines.append("\n📋 خروجی واقعی getMyCommands:")
    for scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ):
        for lang in (None, "fa", "en"):
            try:
                cmds = await bot.get_my_commands(scope=scope, language_code=lang)
            except Exception as e:
                lines.append(f"{type(scope).__name__} lang={lang}: خطا ({e})")
                continue
            names = [c.command for c in cmds] or "(خالی)"
            lines.append(f"{type(scope).__name__} lang={lang}: {names}")

    text = "\n".join(lines)
    for i in range(0, len(text), 3500):
        await message.answer(text[i:i + 3500])

# Matches a plain integer, or one with a 2-decimal remainder (bank SMS text
# writes amounts as "503,00 TL" / "503.00 TRY" / just "503") — only the
# whole-number part is kept, since utils.pricing.unique_amount only ever
# produces whole numbers.
_AMOUNT_RE = re.compile(r"\d+(?:[.,]\d{2})?")


def _candidate_amounts(text: str) -> set[int]:
    amounts = set()
    for raw in _AMOUNT_RE.findall(text):
        whole = raw.split(",")[0].split(".")[0]
        if whole.isdigit():
            amounts.add(int(whole))
    return amounts


def _admin_text_message(message: Message) -> bool:
    return (
        bool(message.text)
        and not message.text.startswith("/")
        and message.from_user.id in config.ADMIN_IDS
    )


@router.message(_admin_text_message)
async def maybe_match_payment(message: Message, bot: Bot):
    """An admin's phone (MacroDroid or any similar SMS-forwarding tool) can
    forward bank-deposit notification text straight into a chat with this
    bot. Every pending order already has a unique exact amount
    (utils.pricing.unique_amount), so any number found in the forwarded
    text that matches one unambiguously identifies the order — there's no
    need to parse the bank's specific wording.

    Silently does nothing when no number in the message matches any
    currently-pending order, so this never interferes with an admin's
    ordinary use of the bot (typing commands, replying to support, etc.);
    this handler is also registered last in this bot's routers, so any
    more specific flow already in progress claims the message first.
    """
    for amount in _candidate_amounts(message.text):
        order = db.get_pending_order_by_amount(amount)
        if not order:
            continue

        if not db.auto_approve_enabled():
            await message.answer(
                f"💳 واریز {amount:,} {config.CURRENCY_LABEL} با سفارش #{order['id']} مطابقت داره، "
                "ولی تایید خودکار خاموشه — از «📤 سفارش‌های معطل» دستی تاییدش کن."
            )
            return

        ok, detail = await provision_order(bot, order["id"])
        if ok:
            await message.answer(
                f"✅ سفارش #{order['id']} خودکار تایید و تحویل داده شد "
                f"(واریز {amount:,} {config.CURRENCY_LABEL})."
            )
        else:
            log.error("auto-approve provisioning failed for order %s: %s", order["id"], detail)
            await message.answer(
                f"⚠️ واریز {amount:,} با سفارش #{order['id']} مطابقت داشت ولی تحویل خودکار ناموفق بود: "
                f"{detail}\nاز «📤 سفارش‌های معطل» دستی بررسی کن."
            )
        return
