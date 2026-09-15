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
