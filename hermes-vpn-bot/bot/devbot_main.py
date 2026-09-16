import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
import db
from handlers import devmenu, ops


async def main():
    logging.basicConfig(level=logging.INFO)

    if not config.DEV_BOT_TOKEN:
        raise SystemExit("DEV_BOT_TOKEN is not set — add it to .env and restart.")
    if not config.ADMIN_IDS:
        raise SystemExit("ADMIN_IDS is empty — this bot only answers admins, so nobody could use it.")

    db.init_db()

    bot = Bot(token=config.DEV_BOT_TOKEN)
    dp = Dispatcher()

    # devmenu first: its pending-action dispatcher only fires when an admin
    # has an open multi-step flow, so it never shadows ops.py's plain
    # /commands either way — but this keeps the menu's own crash reporter
    # first in line for its own buttons.
    dp.include_router(devmenu.router)
    dp.include_router(ops.router)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
