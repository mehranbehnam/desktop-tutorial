import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, BotCommandScopeChat

import config
import db
from handlers import admin, buy, ops, renew, start, status, trial

# Shown to every user via the ☰ menu button next to the message box.
COMMANDS_DEFAULT = [
    BotCommand(command="start", description="شروع و نمایش منو"),
    BotCommand(command="stop", description="لغو / بازگشت به منو"),
]
# Extra commands shown only in an admin's own chat with the bot.
COMMANDS_ADMIN_EXTRA = [
    BotCommand(command="report", description="گزارش مالی ۲۴ ساعت اخیر"),
]


async def _setup_commands(bot: Bot):
    await bot.set_my_commands(COMMANDS_DEFAULT)
    for admin_id in config.ADMIN_IDS:
        try:
            await bot.set_my_commands(
                COMMANDS_DEFAULT + COMMANDS_ADMIN_EXTRA,
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logging.exception("failed to set admin command menu for %s", admin_id)


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

    await _setup_commands(bot)

    # False, not True: /update and /restartxray restart this process often,
    # and a command sent in that few-second window must still be picked up
    # once polling resumes, not silently discarded.
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
