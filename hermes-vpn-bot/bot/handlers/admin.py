import logging
import re

from aiogram import Bot, Router
from aiogram.types import Message

import config
import db
from handlers.buy import provision_order

router = Router()
log = logging.getLogger(__name__)

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
