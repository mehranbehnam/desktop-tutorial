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
        text = f"{plan['label']} — {plan['price']:,} {config.CURRENCY_LABEL}"
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
