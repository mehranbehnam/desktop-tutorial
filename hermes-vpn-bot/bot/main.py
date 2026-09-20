import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonCommands

import config
import db
from handlers import admin, buy, renew, start, status, trial

# Shown to every user via the ☰ menu button next to the message box. This is
# the customer-facing sales bot — no server/maintenance commands here at
# all (those live only on the separate developer bot, devbot_main.py).
COMMANDS_DEFAULT = [
    BotCommand(command="start", description="شروع و نمایش منو"),
    BotCommand(command="stop", description="لغو / بازگشت به منو"),
]


async def _setup_commands(bot: Bot):
    # Without this, the ☰ button next to the message box stays the plain
    # keyboard-toggle icon — set_my_commands alone populates the list but
    # doesn't change what that button looks like or does.
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    await bot.set_my_commands(COMMANDS_DEFAULT)


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

    await _setup_commands(bot)

    # False, not True: /update and /restartxray restart this process often,
    # and a command sent in that few-second window must still be picked up
    # once polling resumes, not silently discarded.
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
