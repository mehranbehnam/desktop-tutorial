import asyncio
import logging

from aiogram import Bot, Dispatcher

import config
import db
from handlers import admin, buy, ops, renew, start, status, trial


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

    # False, not True: /update and /restartxray restart this process often,
    # and a command sent in that few-second window must still be picked up
    # once polling resumes, not silently discarded.
    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
