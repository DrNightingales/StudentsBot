from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import Message

from students_crm.db.routines import (
    add_to_whitelist,
    get_invited_users,
    insert_registration_token,
    validate_token_request,
)
from students_crm.students_bot.sync_utils import generate_invite_code, generate_token_fixed
from students_crm.utils.constants import (
    ADMIN_ID,
    BOT_TOKEN_RATE_LIMIT_COUNT,
    BOT_TOKEN_RATE_LIMIT_WINDOW,
    REGISTRATION_URL_BASE,
)
from students_crm.utils.rate_limit import RateLimiter

router = Router()
token_request_limiter = RateLimiter(BOT_TOKEN_RATE_LIMIT_COUNT, BOT_TOKEN_RATE_LIMIT_WINDOW)


def _is_private_chat(message: Message) -> bool:
    return message.chat.type == ChatType.PRIVATE


async def _answer_private_only(message: Message) -> None:
    await message.answer('Эта команда доступна только в личном чате с ботом.')


@router.message(Command('whitelist'), F.from_user.id == ADMIN_ID)
async def command_whitelist_handler(message: Message) -> None:
    """Add usernames from the admin message to the whitelist."""
    if not _is_private_chat(message):
        await _answer_private_only(message)
        return

    if message.text:
        usernames = message.text.split()
        if len(usernames) <= 1:
            await message.answer('Укажите хотя бы одного пользователя для добавления в белый список')
            return
        for tg_username in usernames[1:]:
            invite_code = generate_invite_code()
            res = await add_to_whitelist(tg_username, invite_code)
            if not res:
                await message.answer(str(res))


@router.message(Command('list_invited'), F.from_user.id == ADMIN_ID)
async def command_list_invited_handler(message: Message) -> None:
    """Send reminders to invited users who still need to register."""
    if not _is_private_chat(message):
        await _answer_private_only(message)
        return

    users = await get_invited_users()
    for user in users:
        await message.answer(
            text=f"""
@{user.tg_username}, пожалуйста, зарегистрируйся с помощью команды <code>/register</code> в @drn_students_bot.

Твой инвайт-код: <code>{user.invite_code}</code>
"""
        )


@router.message(Command('register'))
async def command_register_handler(message: Message) -> None:
    """Create a registration token for a Telegram user."""
    if not _is_private_chat(message):
        await _answer_private_only(message)
        return

    if message.from_user and message.text:
        tg_username = message.from_user.username
        tg_id = int(message.from_user.id)
        invite_code_parts = message.text.strip().split(maxsplit=1)
    else:
        await message.answer('Неизвестная ошибка')
        return

    if len(invite_code_parts) == 1 or tg_username is None:
        await message.answer('Использование: /register <инвайт-код>')
        return

    invite_code = invite_code_parts[1]
    if not token_request_limiter.allow(str(tg_id)):
        await message.answer('Слишком много запросов. Попробуйте позже.')
        return

    is_valid_request = await validate_token_request(tg_username, invite_code)
    if not is_valid_request:
        await message.answer(str(is_valid_request))
        return

    token = generate_token_fixed()
    await insert_registration_token(
        tg_username,
        tg_id,
        token,
    )

    link = f'{REGISTRATION_URL_BASE}?token={token}'
    await message.answer(
        f"""
Перейдите по ссылке, чтобы завершить регистрацию:
{link}
    """
    )
