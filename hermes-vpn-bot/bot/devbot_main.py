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
from handlers import admin, buy, clientlist, devmenu, ops, renew, start, status, trial
from utils import cleanup

# Shown via the ☰ menu button next to the message box — kept to just the
# basics (start/menu/cancel/stop). Everything else lives on the
# reply-keyboard category menu (devmenu.MENU) so the ☰ list doesn't
# duplicate it; every one of those commands still works if typed by hand,
# this only controls what's listed in the popup.
COMMANDS = [
    BotCommand(command="start", description="نمایش منوی اصلی"),
    BotCommand(command="menu", description="نمایش منوی اصلی"),
    BotCommand(command="cancel", description="لغو عملیات در حال انجام"),
    BotCommand(command="stop", description="لغو عملیات در حال انجام"),
]


async def main():
    logging.basicConfig(level=logging.INFO)

    if not config.DEV_BOT_TOKEN:
        raise SystemExit("DEV_BOT_TOKEN is not set — add it to .env and restart.")
    if not config.ADMIN_IDS:
        raise SystemExit("ADMIN_IDS is empty — this bot only answers admins, so nobody could use it.")

    db.init_db()

    bot = Bot(token=config.DEV_BOT_TOKEN)
    dp = Dispatcher()
    # Without this, the ☰ button next to the message box stays the plain
    # keyboard-toggle icon — set_my_commands alone populates the list but
    # doesn't change what that button looks like or does.
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    # Wipe every (scope, language_code) combination this bot could have
    # commands under before setting the real list — a command set under a
    # more specific scope (e.g. all-private-chats) or a specific
    # language_code (BotFather lets you set a separate list per language,
    # and this is a Farsi-facing bot), whether by an old version of this
    # code or by hand through @BotFather, outranks a plain default-scope
    # update and would otherwise keep showing up regardless of what
    # COMMANDS is set to. Logging what's left after confirms it worked,
    # or says exactly where a survivor is still coming from.
    scopes = (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    )
    for scope in scopes:
        for lang in (None, "fa", "en"):
            await bot.delete_my_commands(scope=scope, language_code=lang)

    await bot.set_my_commands(COMMANDS)

    for scope in scopes:
        for lang in (None, "fa"):
            leftover = await bot.get_my_commands(scope=scope, language_code=lang)
            if leftover and [c.command for c in leftover] != [c.command for c in COMMANDS]:
                # logging.error, not .warning — "📄 خطاهای اخیر" only shows
                # journalctl -p err, so this needs error level to actually
                # be visible from there.
                logging.error(
                    "stray bot commands survived under scope=%s lang=%s: %s",
                    type(scope).__name__, lang, [c.command for c in leftover],
                )

    # devmenu/ops first: their pending-action dispatchers only fire when an
    # admin has an open multi-step flow, so they never shadow the sales
    # bot's own handlers — but this keeps their crash reporters first in
    # line for their own buttons. The sales-bot routers are included too,
    # unmodified, so this bot can run the whole business on its own if the
    # sales bot is ever down.
    dp.include_router(devmenu.router)
    dp.include_router(ops.router)
    dp.include_router(clientlist.router)
    dp.include_router(start.router)
    dp.include_router(buy.router)
    dp.include_router(renew.router)
    dp.include_router(trial.router)
    dp.include_router(status.router)
    dp.include_router(admin.router)

    # Housekeeping: auto-reject orders stuck "awaiting_review" for 24h+ and
    # auto-delete expired XUI clients (real accounts and expired free-trial
    # ones alike), on a timer — see utils/cleanup.py for why.
    asyncio.create_task(cleanup.cleanup_loop(bot))

    await bot.delete_webhook(drop_pending_updates=False)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
