import asyncio
import logging
import sys


from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

from students_crm.utils.constants import ADMIN_ID, API_KEY
from students_crm.db.routines import init_db
from students_crm.students_bot.homework import router as homework_router
from students_crm.students_bot.registration import router as registration_router

dp = Dispatcher()
dp.include_router(registration_router)
dp.include_router(homework_router)


async def main():
    """Start the bot and begin polling.

    Returns:
        None
    """
    bot = Bot(token=API_KEY, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await init_db()
    await bot.set_my_commands(
        [
            BotCommand(command='homework', description='Домашние задания'),
            BotCommand(command='register', description='Регистрация'),
        ],
        scope=BotCommandScopeDefault(),
    )
    await bot.set_my_commands(
        [
            BotCommand(command='assignments', description='Управление заданиями'),
            BotCommand(command='homework', description='Домашние задания'),
            BotCommand(command='register', description='Регистрация'),
        ],
        scope=BotCommandScopeChat(chat_id=ADMIN_ID),
    )
    await dp.start_polling(bot)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
