import aiosqlite as sql
import logging
from collections import namedtuple
from dataclasses import dataclass
from students_crm.db.schemas import db_schemas
from students_crm.utilities.constants import DB_PATH

Invite = namedtuple('Invite', ['username', 'invite_code'])


@dataclass
class Result:
    """Represents the outcome of an operation."""

    ok: bool
    message: str | None

    def __bool__(self):
        return self.ok

    def __str__(self):
        return self.message


async def init_db():
    """Create required database tables if they do not exist.

    Returns:
        None
    """
    try:
        async with sql.connect(DB_PATH) as db:
            await db.execute(db_schemas['whitelist'])
            await db.execute(db_schemas['users'])
            await db.execute(db_schemas['registration_tokens'])
            await db.commit()
    except Exception as e:
        logging.log(level=logging.ERROR, msg=e)


async def get_invited_useres() -> list[Invite]:
    """Fetch whitelist entries whose invite codes are unused.

    Returns:
        list[Invite]: Pending users with their invite codes.
    """
    async with sql.connect(DB_PATH) as db:
        rows = await db.execute_fetchall('SELECT username, invite_code FROM whitelist WHERE used = 0')
        return [Invite(username=row[0], invite_code=row[1]) for row in rows]


async def register_user(username: str, password_hash: str, token: str) -> Result:
    """Register a new user using a previously issued token.

    Args:
        username (str): Desired username.
        password_hash (str): Hashed password.
        token (str): Registration token from the bot.

    Returns:
        Result: Operation outcome and optional message.
    """
    tg = await validate_token(token)
    if not tg:
        return Result(False, 'Ваш токен не действителен, используйте комманду /register повторно')
    tg_username, tg_id = tg

    async with sql.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT INTO users (username, tg_id, tg_username, password_hash)
                VALUES (?, ?, ?, ?)
                """,
                (username, tg_id, tg_username, password_hash),
            )
            await db.execute('UPDATE whitelist SET used = 1 WHERE username = ?', (tg_username,))
            await db.execute('DELETE FROM registration_tokens WHERE token = ?', (token,))
            await db.commit()
        except Exception as exc:
            logging.log(level=logging.ERROR, msg=exc)
            return Result(False, str(exc))
    return Result(True, None)


async def validate_token(token: str) -> tuple[str, int] | None:
    """Validate a registration token and return Telegram metadata.

    Args:
        token (str): Token to check.

    Returns:
        tuple[str, int] | None: Telegram username and id if valid, otherwise None.
    """
    async with sql.connect(DB_PATH) as db:
        db.row_factory = sql.Row
        rows = tuple(await db.execute_fetchall(
            """
            SELECT tg_username, tg_id
            FROM registration_tokens WHERE token = ?
              AND used = 0
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            """,
            (token,),
        ))
        if len(rows) > 0:
            row = rows[0]
            return (row['tg_username'], row['tg_id'])
    return None


async def insert_registrarion_token(tg_username: str, tg_id: int, token: str, grace_period: int = 600):
    """Store a registration token for a Telegram user.

    Args:
        tg_username (str): Telegram username.
        tg_id (int): Telegram user id.
        token (str): Generated token.
        grace_period (int, optional): Seconds until expiration. Defaults to 600.

    Returns:
        None
    """
    expires_at = f'+{grace_period} seconds'
    async with sql.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO registration_tokens (token, tg_username, tg_id, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
            """,
            (token, tg_username, tg_id, expires_at),
        )
        await db.commit()


async def validate_token_request(tg_username: str, invite_code: str) -> Result:
    """Validate that a Telegram user can request a registration token.

    Args:
        tg_username (str): Telegram username requesting access.
        invite_code (str): Provided invite code.

    Returns:
        Result: Validation outcome.
    """
    async with sql.connect(DB_PATH) as db:
        rows = tuple(await db.execute_fetchall(
            """
            SELECT used FROM whitelist WHERE (username = ? AND invite_code = ?)
            """,
            (tg_username, invite_code),
        ))
        if len(rows) == 0:
            return Result(False, 'Неверный пригласительный код или ваш пользователь не находится в белом списке.')
        if rows[0][0] != 0:
            return Result(False, 'Вы уже зарегестрированы.')
        return Result(True, 'Регистрация разрешена')
