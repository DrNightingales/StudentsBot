import aiosqlite as sql
import logging
import sqlite3
from collections import namedtuple
from dataclasses import dataclass
from students_crm.db.schemas import db_schemas
from students_crm.utils.constants import DB_PATH

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


async def _with_db(fn, *args, **kwargs):
    async with sql.connect(DB_PATH) as db:
        return await fn(db, *args, **kwargs)


async def _init_db(db: sql.Connection):
    try:
        await db.execute(db_schemas['whitelist'])
        await db.execute(db_schemas['users'])
        await db.execute(db_schemas['registration_tokens'])
        await db.commit()
    except Exception as e:
        logging.log(level=logging.ERROR, msg=e)


async def init_db():
    """Create required database tables if they do not exist.

    Returns:
        None
    """
    return await _with_db(_init_db)


async def _get_invited_useres(db: sql.Connection) -> list[Invite]:
    rows = await db.execute_fetchall('SELECT username, invite_code FROM whitelist WHERE used = 0')
    return [Invite(username=row[0], invite_code=row[1]) for row in rows]


async def get_invited_useres() -> list[Invite]:
    """Fetch whitelist entries whose invite codes are unused.

    Returns:
        list[Invite]: Pending users with their invite codes.
    """
    return await _with_db(_get_invited_useres)


async def _register_user(
    db: sql.Connection,
    username: str,
    password_hash: str,
    token: str,
) -> Result:
    tg = await _validate_token(db, token)
    if not tg:
        return Result(False, 'Ваш токен не действителен, используйте комманду /register повторно')
    tg_username, tg_id = tg

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


async def register_user(username: str, password_hash: str, token: str) -> Result:
    """Register a new user using a previously issued token.

    Args:
        username (str): Desired username.
        password_hash (str): Hashed password.
        token (str): Registration token from the bot.

    Returns:
        Result: Operation outcome and optional message.
    """
    return await _with_db(_register_user, username, password_hash, token)


async def _validate_token(db: sql.Connection, token: str) -> tuple[str, int] | None:
    db.row_factory = sql.Row
    rows = tuple(
        await db.execute_fetchall(
            """
            SELECT tg_username, tg_id
            FROM registration_tokens WHERE token = ?
              AND used = 0
              AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            """,
            (token,),
        )
    )
    if len(rows) > 0:
        row = rows[0]
        return (row['tg_username'], row['tg_id'])
    return None


async def validate_token(token: str) -> tuple[str, int] | None:
    """Validate a registration token and return Telegram metadata.

    Args:
        token (str): Token to check.

    Returns:
        tuple[str, int] | None: Telegram username and id if valid, otherwise None.
    """
    return await _with_db(_validate_token, token)


async def _insert_registrarion_token(
    db: sql.Connection,
    tg_username: str,
    tg_id: int,
    token: str,
    grace_period: int = 600,
):
    expires_at = f'+{grace_period} seconds'
    await db.execute(
        """
            INSERT INTO registration_tokens (token, tg_username, tg_id, expires_at)
            VALUES (?, ?, ?, datetime('now', ?))
            """,
        (token, tg_username, tg_id, expires_at),
    )
    await db.commit()


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
    return await _with_db(_insert_registrarion_token, tg_username, tg_id, token, grace_period)


async def _validate_token_request(
    db: sql.Connection,
    tg_username: str,
    invite_code: str,
) -> Result:
    rows = tuple(
        await db.execute_fetchall(
            """
            SELECT used FROM whitelist WHERE (username = ? AND invite_code = ?)
            """,
            (tg_username, invite_code),
        )
    )
    if len(rows) == 0:
        return Result(False, 'Неверный пригласительный код или ваш пользователь не находится в белом списке.')
    if rows[0][0] != 0:
        return Result(False, 'Вы уже зарегестрированы.')
    return Result(True, 'Регистрация разрешена')


async def validate_token_request(tg_username: str, invite_code: str) -> Result:
    """Validate that a Telegram user can request a registration token.

    Args:
        tg_username (str): Telegram username requesting access.
        invite_code (str): Provided invite code.

    Returns:
        Result: Validation outcome.
    """
    return await _with_db(_validate_token_request, tg_username, invite_code)


async def _add_to_whitelist(
    db: sql.Connection,
    tg_username: str,
    invite_code: str,
) -> Result:
    try:
        await db.execute(
            'INSERT INTO whitelist (tg_username, invite_code) VALUES (?, ?)',
            (tg_username, invite_code),
        )
        await db.commit()
    except sqlite3.IntegrityError as e:
        if 'UNIQUE' in e.sqlite_errorname:
            return Result(False, f'User {tg_username} is already in the whitelist')
        logging.log(level=logging.ERROR, msg=f'sqlite3.IntegrityError:{e}')
    return Result(True, None)


async def add_to_whitelist(tg_username: str, invite_code: str) -> Result:
    return await _with_db(_add_to_whitelist, tg_username, invite_code)
