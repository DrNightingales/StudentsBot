import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import aiosqlite as sql

from students_crm.db.schemas import db_schemas
from students_crm.utils.constants import DB_PATH


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sql.Connection], Awaitable[None]]


async def _ensure_migrations_table(db: sql.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    await db.commit()


async def _table_exists(db: sql.Connection, table_name: str) -> bool:
    rows = await db.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return bool(rows)


async def _column_exists(db: sql.Connection, table_name: str, column_name: str) -> bool:
    rows = await db.execute_fetchall(f'PRAGMA table_info({table_name})')
    return any(row[1] == column_name for row in rows)


async def _bootstrap_schema(db: sql.Connection) -> None:
    for schema in db_schemas.values():
        await db.execute(schema)


async def _homework_status_russian(db: sql.Connection) -> None:
    if not await _table_exists(db, 'homework_assignments'):
        return
    if not await _column_exists(db, 'homework_assignments', 'status'):
        await db.execute(
            "ALTER TABLE homework_assignments ADD COLUMN status TEXT NOT NULL DEFAULT 'Не решено'",
        )
    await db.execute(
        """
        UPDATE homework_assignments
        SET status = CASE
            WHEN status IS NULL OR status = '' THEN 'Не решено'
            WHEN status = 'assigned' THEN 'Не решено'
            WHEN status = 'submitted' THEN 'На проверке'
            WHEN status = 'Решено (на проверке)' THEN 'На проверке'
            WHEN status = 'Верно' THEN 'Пройдено'
            WHEN status = 'Неверно' THEN 'Провалено'
            ELSE status
        END
        """
    )


async def _homework_status_v2(db: sql.Connection) -> None:
    if not await _table_exists(db, 'homework_assignments'):
        return
    if not await _column_exists(db, 'homework_assignments', 'template_id'):
        await db.execute(
            'ALTER TABLE homework_assignments ADD COLUMN template_id INTEGER REFERENCES homework_templates(id)',
        )
    await db.execute('PRAGMA foreign_keys=OFF')
    await db.execute(
        """
        CREATE TABLE homework_assignments_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER REFERENCES homework_templates(id),
            student_tg_id INTEGER NOT NULL REFERENCES users(tg_id),
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            soft_deadline TEXT NOT NULL,
            hard_deadline TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Не решено'
                CHECK (status IN ('Не решено', 'На проверке', 'Пройдено', 'Провалено')),
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    await db.execute(
        """
        INSERT INTO homework_assignments_new (
            id, template_id, student_tg_id, title, text, soft_deadline, hard_deadline, status, created_at
        )
        SELECT
            id,
            template_id,
            student_tg_id,
            COALESCE(title, 'Без названия'),
            COALESCE(text, ''),
            COALESCE(soft_deadline, datetime('now')),
            COALESCE(hard_deadline, datetime('now')),
            CASE
                WHEN status IS NULL OR status = '' THEN 'Не решено'
                WHEN status = 'assigned' THEN 'Не решено'
                WHEN status IN ('submitted', 'Решено (на проверке)', 'На проверке') THEN 'На проверке'
                WHEN status IN ('Верно', 'Пройдено') THEN 'Пройдено'
                WHEN status IN ('Неверно', 'Провалено') THEN 'Провалено'
                ELSE 'Не решено'
            END,
            COALESCE(created_at, datetime('now'))
        FROM homework_assignments
        """
    )
    await db.execute('DROP TABLE homework_assignments')
    await db.execute('ALTER TABLE homework_assignments_new RENAME TO homework_assignments')
    await db.execute('PRAGMA foreign_keys=ON')


async def _homework_assignment_title(db: sql.Connection) -> None:
    if not await _table_exists(db, 'homework_assignments'):
        return
    if not await _column_exists(db, 'homework_assignments', 'title'):
        await db.execute(
            "ALTER TABLE homework_assignments ADD COLUMN title TEXT NOT NULL DEFAULT 'Без названия'",
        )
    await db.execute(
        """
        UPDATE homework_assignments
        SET title = 'Без названия'
        WHERE title IS NULL OR title = ''
        """
    )


async def _homework_templates_schema(db: sql.Connection) -> None:
    await db.execute(db_schemas['homework_templates'])
    await db.execute(db_schemas['homework_questions'])
    await db.execute(db_schemas['homework_question_attachments'])
    await db.execute(db_schemas['homework_question_options'])
    await db.execute(db_schemas['homework_assignment_attempts'])
    await db.execute(db_schemas['homework_attempt_attachments'])
    await db.execute(db_schemas['homework_attempt_options'])
    if await _table_exists(db, 'homework_assignments'):
        if not await _column_exists(db, 'homework_assignments', 'template_id'):
            await db.execute(
                'ALTER TABLE homework_assignments ADD COLUMN template_id INTEGER REFERENCES homework_templates(id)',
            )


async def _homework_question_points(db: sql.Connection) -> None:
    if not await _table_exists(db, 'homework_questions'):
        return
    if not await _column_exists(db, 'homework_questions', 'points'):
        await db.execute(
            'ALTER TABLE homework_questions ADD COLUMN points REAL NOT NULL DEFAULT 1',
        )
    await db.execute(
        """
        UPDATE homework_questions
        SET points = 1
        WHERE points IS NULL
        """
    )


async def _assignment_indexes(db: sql.Connection) -> None:
    if await _table_exists(db, 'homework_assignments'):
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_assignments_student_status '
            'ON homework_assignments(student_tg_id, status)',
        )
    if await _table_exists(db, 'homework_assignment_attempts'):
        await db.execute(
            'CREATE INDEX IF NOT EXISTS idx_attempts_assignment_student '
            'ON homework_assignment_attempts(assignment_id, student_tg_id)',
        )


async def _account_provisioning_table(db: sql.Connection) -> None:
    await db.execute(db_schemas['account_provisioning'])


MIGRATIONS = [
    Migration(1, 'bootstrap_schema', _bootstrap_schema),
    Migration(2, 'homework_status_russian', _homework_status_russian),
    Migration(3, 'homework_assignment_title', _homework_assignment_title),
    Migration(4, 'homework_templates_schema', _homework_templates_schema),
    Migration(5, 'homework_status_v2', _homework_status_v2),
    Migration(6, 'homework_question_points', _homework_question_points),
    Migration(7, 'assignment_indexes', _assignment_indexes),
    Migration(8, 'account_provisioning_table', _account_provisioning_table),
]


async def run_migrations(db: sql.Connection) -> list[int]:
    await _ensure_migrations_table(db)
    rows = await db.execute_fetchall('SELECT version FROM schema_migrations')
    applied = {row[0] for row in rows}
    applied_now: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        await migration.apply(db)
        await db.execute(
            'INSERT INTO schema_migrations (version, name) VALUES (?, ?)',
            (migration.version, migration.name),
        )
        await db.commit()
        applied_now.append(migration.version)
    return applied_now


async def migrate_db() -> list[int]:
    async with sql.connect(DB_PATH) as db:
        return await run_migrations(db)


def main() -> None:
    try:
        applied = asyncio.run(migrate_db())
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        raise
    if applied:
        print(f'Applied migrations: {applied}')
    else:
        print('No migrations to apply.')


if __name__ == '__main__':
    main()
