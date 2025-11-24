import aiosqlite as sql
import pytest
import pytest_asyncio

import students_crm.db.routines as r
from students_crm.db.schemas import db_schemas


async def _ensure_username_column(db_conn: sql.Connection):
    columns = await db_conn.execute_fetchall('PRAGMA table_info(whitelist)')
    if not any(column[1] == 'username' for column in columns):
        await db_conn.execute('ALTER TABLE whitelist ADD COLUMN username TEXT')
    await db_conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS whitelist_username_sync
        AFTER INSERT ON whitelist
        FOR EACH ROW
        BEGIN
            UPDATE whitelist SET username = NEW.tg_username WHERE id = NEW.id;
        END;
        """
    )
    await db_conn.execute('UPDATE whitelist SET username = tg_username WHERE username IS NULL')


async def _insert_whitelist_entry(
    db_conn: sql.Connection,
    username: str,
    invite_code: str,
    used: int = 0,
):
    await db_conn.execute(
        'INSERT INTO whitelist (tg_username, invite_code, username, used) VALUES (?, ?, ?, ?)',
        (username, invite_code, username, used),
    )
    await db_conn.commit()


async def _insert_token(
    db_conn: sql.Connection,
    token: str,
    tg_username: str,
    tg_id: int,
    expires_in: str = '+600 seconds',
    used: int = 0,
):
    await db_conn.execute(
        """
        INSERT INTO registration_tokens (token, tg_username, tg_id, expires_at, used)
        VALUES (?, ?, ?, datetime('now', ?), ?)
        """,
        (token, tg_username, tg_id, expires_in, used),
    )
    await db_conn.commit()


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    db_file = tmp_path / 'mock_students.db'
    async with sql.connect(db_file.as_posix()) as db_conn:
        for schema in db_schemas.values():
            await db_conn.execute(schema)
        await _ensure_username_column(db_conn)
        await db_conn.commit()
        monkeypatch.setattr(r, 'DB_PATH', db_file.as_posix())
        yield db_conn


@pytest.mark.asyncio
async def test__with_db_runs_callable(db: sql.Connection):
    async def core(conn: sql.Connection, username: str):
        await conn.execute(
            'INSERT INTO whitelist (tg_username, invite_code) VALUES (?, ?)',
            (username, 'CODE-1'),
        )
        await conn.commit()
        return username

    result = await r._with_db(core, 'tg_user')
    assert result == 'tg_user'
    rows = await db.execute_fetchall('SELECT username, invite_code FROM whitelist')
    assert rows == [('tg_user', 'CODE-1')]


@pytest.mark.asyncio
async def test__init_db_creates_missing_tables(db: sql.Connection):
    for table in ('whitelist', 'users', 'registration_tokens'):
        await db.execute(f'DROP TABLE IF EXISTS {table}')
    await db.commit()

    await r._init_db(db)

    tables = {
        row[0]
        for row in await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"
        )
    }
    assert {'whitelist', 'users', 'registration_tokens'}.issubset(tables)


@pytest.mark.asyncio
async def test_init_db_wrapper_uses_helper(db: sql.Connection):
    for table in ('whitelist', 'users', 'registration_tokens'):
        await db.execute(f'DROP TABLE IF EXISTS {table}')
    await db.commit()

    await r.init_db()

    tables = {
        row[0]
        for row in await db.execute_fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' AND name!='sqlite_sequence'"
        )
    }
    assert {'whitelist', 'users', 'registration_tokens'}.issubset(tables)


@pytest.mark.asyncio
async def test__get_invited_useres_filters_used_entries(db: sql.Connection):
    await _insert_whitelist_entry(db, 'allowed_user', 'CODE-1', used=0)
    await _insert_whitelist_entry(db, 'registered_user', 'CODE-2', used=1)

    invites = await r._get_invited_useres(db)

    assert invites == [r.Invite(tg_username='allowed_user', invite_code='CODE-1')]


@pytest.mark.asyncio
async def test_get_invited_useres_wrapper_reads_from_db(db: sql.Connection):
    await _insert_whitelist_entry(db, 'wrapped_user', 'WRAP', used=0)
    await _insert_whitelist_entry(db, 'wrapped_user_used', 'WRAP2', used=1)

    invites = await r.get_invited_useres()

    assert invites == [r.Invite(tg_username='wrapped_user', invite_code='WRAP')]


@pytest.mark.asyncio
async def test__add_to_whitelist_inserts_new_user(db: sql.Connection):
    result = await r._add_to_whitelist(db, 'new_whitelist_user', 'CODE-3')
    assert result.ok is True

    row = await db.execute_fetchall('SELECT username, invite_code, used FROM whitelist')
    assert row == [('new_whitelist_user', 'CODE-3', 0)]


@pytest.mark.asyncio
async def test__add_to_whitelist_rejects_duplicates(db: sql.Connection):
    await r._add_to_whitelist(db, 'duplicate_user', 'CODE-4')
    result = await r._add_to_whitelist(db, 'duplicate_user', 'CODE-4')

    assert result.ok is False
    assert 'whitelist' in (result.message or '')


@pytest.mark.asyncio
async def test_add_to_whitelist_wrapper_inserts(db: sql.Connection):
    result = await r.add_to_whitelist('wrapper_user', 'WRP-1')
    assert result.ok is True

    row = await db.execute_fetchall('SELECT username FROM whitelist WHERE username = ?', ('wrapper_user',))
    assert row == [('wrapper_user',)]


@pytest.mark.asyncio
async def test__validate_token_request_checks_invite(db: sql.Connection):
    await _insert_whitelist_entry(db, 'token_user', 'INV-1', used=0)

    allowed = await r._validate_token_request(db, 'token_user', 'INV-1')
    denied = await r._validate_token_request(db, 'token_user', 'WRONG')

    assert allowed.ok is True
    assert denied.ok is False


@pytest.mark.asyncio
async def test_validate_token_request_wrapper(db: sql.Connection):
    await _insert_whitelist_entry(db, 'wrapped_token_user', 'INV-2', used=0)

    allowed = await r.validate_token_request('wrapped_token_user', 'INV-2')
    assert allowed.ok is True


@pytest.mark.asyncio
async def test__insert_registrarion_token_persists_token(db: sql.Connection):
    await r._insert_registrarion_token(db, 'tg_name', 1001, 'token-1', grace_period=60)

    row = await db.execute_fetchall('SELECT token, tg_username, tg_id FROM registration_tokens')
    assert row == [('token-1', 'tg_name', 1001)]


@pytest.mark.asyncio
async def test_insert_registrarion_token_wrapper(db: sql.Connection):
    await r.insert_registrarion_token('wrapper_tg', 2002, 'token-2', grace_period=120)

    row = await db.execute_fetchall('SELECT token FROM registration_tokens WHERE token = ?', ('token-2',))
    assert row == [('token-2',)]


@pytest.mark.asyncio
async def test__validate_token_returns_tuple(db: sql.Connection):
    await _insert_token(db, 'token-3', 'tg_valid', 3003)

    result = await r._validate_token(db, 'token-3')
    assert result == ('tg_valid', 3003)

    missing = await r._validate_token(db, 'missing')
    assert missing is None


@pytest.mark.asyncio
async def test_validate_token_wrapper(db: sql.Connection):
    await _insert_token(db, 'token-4', 'tg_wrapper', 4004)

    result = await r.validate_token('token-4')
    assert result == ('tg_wrapper', 4004)


@pytest.mark.asyncio
async def test__register_user_creates_user_and_cleansup_token(db: sql.Connection):
    await _insert_whitelist_entry(db, 'tg_student', 'INV-3', used=0)
    await _insert_token(db, 'token-5', 'tg_student', 5005)

    result = await r._register_user(db, 'app_user', 'pwd_hash', 'token-5')

    assert result.ok is True
    user_row = await db.execute_fetchall(
        'SELECT username, tg_id, tg_username FROM users WHERE username = ?', ('app_user',)
    )
    assert list(*user_row) == ['app_user', 5005, 'tg_student']

    whitelist_row = await db.execute_fetchall('SELECT used FROM whitelist WHERE username = ?', ('tg_student',))
    assert list(*whitelist_row) == [1]

    tokens_left = await db.execute_fetchall('SELECT COUNT(*) FROM registration_tokens WHERE token = ?', ('token-5',))
    assert list(*tokens_left) == [0]


@pytest.mark.asyncio
async def test__register_user_rejects_invalid_token(db: sql.Connection):
    result = await r._register_user(db, 'app_user', 'pwd_hash', 'missing-token')

    assert result.ok is False
    assert 'токен' in (result.message or '')


@pytest.mark.asyncio
async def test_register_user_wrapper(db: sql.Connection):
    await _insert_whitelist_entry(db, 'tg_student_wrapper', 'INV-4', used=0)
    await _insert_token(db, 'token-6', 'tg_student_wrapper', 6006)

    result = await r.register_user('wrapped_app_user', 'hash', 'token-6')
    assert result.ok is True

    users = await db.execute_fetchall('SELECT username FROM users WHERE username = ?', ('wrapped_app_user',))
    assert users == [('wrapped_app_user',)]
