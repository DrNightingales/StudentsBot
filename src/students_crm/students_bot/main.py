import asyncio
import logging
import sys


from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from students_crm.db.routines import init_db
from students_crm.students_bot.registration import router as registration_router
from students_crm.utils.constants import API_KEY


dp = Dispatcher()
dp.include_router(registration_router)


async def main():
    """Start the bot and begin polling.

    Returns:
        None
    """
    bot = Bot(token=API_KEY, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await init_db()
    await dp.start_polling(bot)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    asyncio.run(main())
