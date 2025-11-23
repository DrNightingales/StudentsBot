import asyncio
import logging
import sqlite3
import sys


import aiosqlite as sql
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

from students_crm.utilities.constants import ADMIN_ID, DB_PATH, REGISTRATION_URL_BASE, API_KEY
from students_crm.db.db import get_invited_useres, init_db, insert_registrarion_token, validate_token_request
from students_crm.students_bot.sync_utils import generate_invite_code, generate_token_fixed

dp = Dispatcher()


@dp.message(Command('whitelist'), F.from_user.id == ADMIN_ID)
async def command_whitelist_handler(message: Message) -> None:
    """Add usernames from the admin message to the whitelist.

    Args:
        message (Message): Admin command message.

    Returns:
        None
    """
    if message.text:
        usernames = message.text.split()
        if len(usernames) <= 1:
            await message.answer('Please provide at least one username to add to the whitelist')
        for username in usernames[1:]:
            invite_code = generate_invite_code()
            async with sql.connect(DB_PATH) as db:
                try:
                    await db.execute(
                        'INSERT INTO whitelist (username, invite_code) VALUES (?, ?)',
                        (username, invite_code),
                    )
                    await db.commit()
                except sqlite3.IntegrityError as exc:
                    if 'UNIQUE' in exc.sqlite_errorname:
                        await message.answer(f'User {username} is already in the whitelist')
                        return
                    logging.log(level=logging.ERROR, msg=f'sqlite3.IntegrityError:{exc}')


@dp.message(Command('list_invited'), F.from_user.id == ADMIN_ID)
async def command_list_invited_handler(message: Message) -> None:
    """Send reminders to invited users who still need to register.

    Args:
        message (Message): Admin command message.

    Returns:
        None
    """
    users = await get_invited_useres()
    for user in users:
        await message.answer(
            text=f"""
@{user.username}, пожалуйста, зарегистрируйся с помощью команды <code>/register</code> в @drn_students_bot.

Твой инвайт-код: <code>{user.invite_code}</code>
"""
        )


@dp.message(Command('register'))
async def command_register_handler(message: Message) -> None:
    """Create a registration token for a Telegram user.

    Args:
        message (Message): User command message.

    Returns:
        None
    """
    if message.from_user and message.text:
        tg_username = message.from_user.username
        tg_id = int(message.from_user.id)
        invite_code_parts = message.text.strip().split(maxsplit=1)
    else:
        await message.answer('Unknown error')
        return

    if len(invite_code_parts) == 1 or tg_username is None:
        await message.answer('usage: /register invite_code')
        return

    invite_code = invite_code_parts[1]

    is_valid_request = await validate_token_request(tg_username, invite_code)
    if not is_valid_request:
        await message.answer(str(is_valid_request))
        return

    token = generate_token_fixed()
    await insert_registrarion_token(
        tg_username,
        tg_id,
        token,
    )

    link = f'{REGISTRATION_URL_BASE}?token={token}'
    await message.answer(
        f"""
Перейдите по сслыке, чтобы завершить регистрацию:
{link}
    """
    )


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
