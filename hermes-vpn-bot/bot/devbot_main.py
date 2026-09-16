import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
import db
from handlers import admin, buy, devmenu, ops, renew, start, status, trial


async def main():
    logging.basicConfig(level=logging.INFO)

    if not config.DEV_BOT_TOKEN:
        raise SystemExit("DEV_BOT_TOKEN is not set — add it to .env and restart.")
    if not config.ADMIN_IDS:
        raise SystemExit("ADMIN_IDS is empty — this bot only answers admins, so nobody could use it.")

    db.init_db()

    bot = Bot(token=config.DEV_BOT_TOKEN)
    dp = Dispatcher()

    # devmenu/ops first: their pending-action dispatchers only fire when an
    # admin has an open multi-step flow, so they never shadow the sales
    # bot's own handlers — but this keeps their crash reporters first in
    # line for their own buttons. The sales-bot routers are included too,
    # unmodified, so this bot can run the whole business on its own if the
    # sales bot is ever down.
    dp.include_router(devmenu.router)
    dp.include_router(ops.router)
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(renew.router)
    dp.include_router(trial.router)
    dp.include_router(status.router)
    dp.include_router(admin.router)

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
