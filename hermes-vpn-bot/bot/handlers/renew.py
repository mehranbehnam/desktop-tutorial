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
        f"مبلغ قابل پرداخت — دقیقاً همین عدد:\n💰 {amount:,} {config.CURRENCY_LABEL}\n\n"
        f"شماره کارت:\n💳 {config.CARD_NUMBER}\n👤 به نام: {config.CARD_OWNER}\n\n"
        "بعد از واریز، رسید رو همینجا بفرست.\n"
        f"(شماره سفارش: #{order_id})"
    )
    await callback.message.answer(text)
    await callback.answer()
