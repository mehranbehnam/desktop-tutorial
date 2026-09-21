import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

import config
import db
from handlers import admin, buy, clientlist, renew, start, status, trial

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

    # A command set at one time (by this code, an older version of it, or
    # by hand through @BotFather's "Edit Commands") can be scoped more
    # specifically than BotCommandScopeDefault (e.g. all-private-chats),
    # or set for a specific language_code (BotFather lets you set a
    # separate command list per language, and this is a Farsi-facing
    # bot) — either one outranks a plain default-scope, no-language
    # update and keeps showing. Wiping every (scope, language_code)
    # combination this bot could plausibly have commands under, and
    # logging what get_my_commands actually reports for each right
    # after, means a stray command either provably goes away here or
    # the next restart's log says exactly where it's still coming from.
    scopes = (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    )
    for scope in scopes:
        for lang in (None, "fa", "en"):
            await bot.delete_my_commands(scope=scope, language_code=lang)

    await bot.set_my_commands(COMMANDS_DEFAULT)

    for scope in scopes:
        for lang in (None, "fa"):
            leftover = await bot.get_my_commands(scope=scope, language_code=lang)
            if leftover and [c.command for c in leftover] != [c.command for c in COMMANDS_DEFAULT]:
                # logging.error, not .warning — "📄 خطاهای اخیر" in the dev
                # bot only shows journalctl -p err, so this needs to be at
                # error level to actually be visible from there.
                logging.error(
                    "stray bot commands survived under scope=%s lang=%s: %s",
                    type(scope).__name__, lang, [c.command for c in leftover],
                )


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
    dp.include_router(clientlist.router)
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
