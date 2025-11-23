import pytest
import pytest_asyncio
import aiosqlite as sql
import students_crm.db.routines as r
from students_crm.db.schemas import db_schemas
import logging

logger = logging.getLogger(__name__)

@pytest_asyncio.fixture
async def db():
    async with sql.connect(':memory:') as db_conn:
        for schema in db_schemas.values():
            await db_conn.execute(schema)
        await db_conn.commit()
        yield db_conn


@pytest.fixture
def tables():
    tables = {(table,) for table in db_schemas.keys()}
    yield tables


@pytest.fixture
def whitelisted_users():
    whitelisted_users = [{'tg_username': 'test_username1', 'invite_code': 'ABCD-EFGH'}]
    yield whitelisted_users


@pytest.mark.asyncio
async def test_list_tables(db: sql.Connection, tables):
    res = set(
        await db.execute_fetchall("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'")
    )
    assert res == tables


@pytest.mark.asyncio
async def test_add_to_whitelist(db: sql.Connection, whitelisted_users):
    await r._add_to_whitelist(whitelisted_users['tg_username'], whitelisted_users['invite_code'])
