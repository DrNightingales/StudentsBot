import aiosqlite as sql
import logging
import sqlite3
from students_crm.db.migrate import run_migrations
from students_crm.db.models import (
    HomeworkAssignmentView,
    HomeworkAttempt,
    HomeworkAttemptAttachment,
    HomeworkOption,
    HomeworkQuestion,
    HomeworkQuestionAttachment,
    HomeworkQuestionProgress,
    HomeworkTemplate,
    Invite,
    ProvisioningStatus,
    Result,
    Student,
)
from students_crm.utils.constants import DB_PATH


async def _with_db(fn, *args, **kwargs):
    async with sql.connect(DB_PATH, timeout=10) as db:
        await db.execute('PRAGMA foreign_keys = ON')
        await db.execute('PRAGMA journal_mode = WAL')
        await db.execute('PRAGMA busy_timeout = 5000')
        return await fn(db, *args, **kwargs)


async def _init_db(db: sql.Connection):
    try:
        await run_migrations(db)
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        raise


async def init_db():
    """Create required database tables if they do not exist.

    Returns:
        None
    """
    return await _with_db(_init_db)


async def _get_invited_users(db: sql.Connection) -> list[Invite]:
    rows = await db.execute_fetchall('SELECT tg_username, invite_code FROM whitelist WHERE used = 0')
    return [Invite(tg_username=row[0], invite_code=row[1]) for row in rows]


async def get_invited_users() -> list[Invite]:
    """Fetch whitelist entries whose invite codes are unused.

    Returns:
        list[Invite]: Pending users with their invite codes.
    """
    return await _with_db(_get_invited_users)


async def _get_invited_useres(db: sql.Connection) -> list[Invite]:
    """Deprecated misspelled alias for `_get_invited_users`."""
    return await _get_invited_users(db)


async def get_invited_useres() -> list[Invite]:
    """Deprecated misspelled alias for `get_invited_users`."""
    return await get_invited_users()


async def _get_registered_students(db: sql.Connection) -> list[Student]:
    rows = await db.execute_fetchall(
        'SELECT username, tg_username, tg_id FROM users ORDER BY username',
    )
    return [Student(username=row[0], tg_username=row[1], tg_id=row[2]) for row in rows]


async def get_registered_students() -> list[Student]:
    """Fetch registered users for admin assignment selection."""
    return await _with_db(_get_registered_students)


async def _create_homework_template(
    db: sql.Connection,
    title: str,
    description: str | None,
    answering_mode: str,
    max_attempts: int,
    created_by_tg_id: int | None,
) -> Result:
    try:
        cursor = await db.execute(
            """
            INSERT INTO homework_templates (
                title, description, answering_mode, max_attempts, created_by_tg_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (title, description, answering_mode, max_attempts, created_by_tg_id),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None, cursor.lastrowid)


async def create_homework_template(
    title: str,
    description: str | None,
    answering_mode: str,
    max_attempts: int,
    created_by_tg_id: int | None,
) -> Result:
    return await _with_db(
        _create_homework_template,
        title,
        description,
        answering_mode,
        max_attempts,
        created_by_tg_id,
    )


async def _get_latest_draft_template(
    db: sql.Connection,
    created_by_tg_id: int,
) -> HomeworkTemplate | None:
    rows = await db.execute_fetchall(
        """
        SELECT id, title, description, answering_mode, max_attempts, is_published
        FROM homework_templates
        WHERE created_by_tg_id = ? AND is_published = 0
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (created_by_tg_id,),
    )
    if not rows:
        return None
    row = rows[0]
    return HomeworkTemplate(*row)


async def get_latest_draft_template(created_by_tg_id: int) -> HomeworkTemplate | None:
    return await _with_db(_get_latest_draft_template, created_by_tg_id)


async def _get_homework_template(db: sql.Connection, template_id: int) -> HomeworkTemplate | None:
    rows = await db.execute_fetchall(
        """
        SELECT id, title, description, answering_mode, max_attempts, is_published
        FROM homework_templates
        WHERE id = ?
        """,
        (template_id,),
    )
    if not rows:
        return None
    return HomeworkTemplate(*rows[0])


async def get_homework_template(template_id: int) -> HomeworkTemplate | None:
    return await _with_db(_get_homework_template, template_id)


async def _list_homework_templates(
    db: sql.Connection,
    *,
    published_only: bool = True,
    created_by_tg_id: int | None = None,
) -> list[HomeworkTemplate]:
    conditions = []
    params: list[object] = []
    if published_only:
        conditions.append('is_published = 1')
    if created_by_tg_id is not None:
        conditions.append('created_by_tg_id = ?')
        params.append(created_by_tg_id)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ''
    rows = await db.execute_fetchall(
        f"""
        SELECT id, title, description, answering_mode, max_attempts, is_published
        FROM homework_templates
        {where_clause}
        ORDER BY created_at DESC
        """,
        tuple(params),
    )
    return [HomeworkTemplate(*row) for row in rows]


async def list_homework_templates(
    *,
    published_only: bool = True,
    created_by_tg_id: int | None = None,
) -> list[HomeworkTemplate]:
    return await _with_db(_list_homework_templates, published_only=published_only, created_by_tg_id=created_by_tg_id)


async def _list_assignment_question_progress(
    db: sql.Connection,
    assignment_id: int,
    student_tg_id: int,
) -> list[HomeworkQuestionProgress]:
    rows = await db.execute_fetchall(
        """
        SELECT q.id,
               q.order_index,
               q.question_type,
               q.points,
               a.attempt_index,
               a.is_correct,
               a.score
        FROM homework_questions q
        LEFT JOIN (
            SELECT ha.question_id, ha.attempt_index, ha.is_correct, ha.score
            FROM homework_assignment_attempts ha
            JOIN (
                SELECT question_id, MAX(attempt_index) AS max_attempt
                FROM homework_assignment_attempts
                WHERE assignment_id = ? AND student_tg_id = ?
                GROUP BY question_id
            ) latest
              ON latest.question_id = ha.question_id
             AND latest.max_attempt = ha.attempt_index
            WHERE ha.assignment_id = ? AND ha.student_tg_id = ?
        ) a ON a.question_id = q.id
        WHERE q.assignment_id = (SELECT template_id FROM homework_assignments WHERE id = ?)
        ORDER BY q.order_index
        """,
        (assignment_id, student_tg_id, assignment_id, student_tg_id, assignment_id),
    )
    progress: list[HomeworkQuestionProgress] = []
    for row in rows:
        attempted = 1 if row[4] is not None else 0
        progress.append(
            HomeworkQuestionProgress(
                question_id=row[0],
                order_index=row[1],
                question_type=row[2],
                points=row[3],
                attempted=attempted,
                is_correct=row[5],
                score=row[6],
            )
        )
    return progress


async def list_assignment_question_progress(
    assignment_id: int,
    student_tg_id: int,
) -> list[HomeworkQuestionProgress]:
    return await _with_db(_list_assignment_question_progress, assignment_id, student_tg_id)


async def _delete_homework_template(db: sql.Connection, template_id: int) -> Result:
    try:
        await db.execute(
            """
            DELETE FROM homework_attempt_options
            WHERE attempt_id IN (
                SELECT id FROM homework_assignment_attempts
                WHERE assignment_id IN (
                    SELECT id FROM homework_assignments WHERE template_id = ?
                )
            )
            """,
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_attempt_attachments
            WHERE attempt_id IN (
                SELECT id FROM homework_assignment_attempts
                WHERE assignment_id IN (
                    SELECT id FROM homework_assignments WHERE template_id = ?
                )
            )
            """,
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_assignment_attempts
            WHERE assignment_id IN (
                SELECT id FROM homework_assignments WHERE template_id = ?
            )
            """,
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_submission_attachments
            WHERE submission_id IN (
                SELECT id FROM homework_submissions
                WHERE assignment_id IN (
                    SELECT id FROM homework_assignments WHERE template_id = ?
                )
            )
            """,
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_submissions
            WHERE assignment_id IN (
                SELECT id FROM homework_assignments WHERE template_id = ?
            )
            """,
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_assignment_attachments
            WHERE assignment_id IN (
                SELECT id FROM homework_assignments WHERE template_id = ?
            )
            """,
            (template_id,),
        )
        await db.execute(
            "DELETE FROM homework_assignments WHERE template_id = ?",
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_question_attachments
            WHERE question_id IN (
                SELECT id FROM homework_questions WHERE assignment_id = ?
            )
            """,
            (template_id,),
        )
        await db.execute(
            """
            DELETE FROM homework_question_options
            WHERE question_id IN (
                SELECT id FROM homework_questions WHERE assignment_id = ?
            )
            """,
            (template_id,),
        )
        await db.execute(
            "DELETE FROM homework_questions WHERE assignment_id = ?",
            (template_id,),
        )
        await db.execute(
            "DELETE FROM homework_templates WHERE id = ?",
            (template_id,),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def delete_homework_template(template_id: int) -> Result:
    return await _with_db(_delete_homework_template, template_id)


async def _publish_homework_template(db: sql.Connection, template_id: int) -> Result:
    try:
        await db.execute(
            "UPDATE homework_templates SET is_published = 1 WHERE id = ?",
            (template_id,),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def publish_homework_template(template_id: int) -> Result:
    return await _with_db(_publish_homework_template, template_id)


async def _update_homework_template_fields(
    db: sql.Connection,
    template_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    answering_mode: str | None = None,
    max_attempts: int | None = None,
) -> Result:
    updates: list[str] = []
    params: list[object] = []
    if title is not None:
        updates.append('title = ?')
        params.append(title)
    if description is not None:
        updates.append('description = ?')
        params.append(description)
    if answering_mode is not None:
        updates.append('answering_mode = ?')
        params.append(answering_mode)
    if max_attempts is not None:
        updates.append('max_attempts = ?')
        params.append(max_attempts)
    if not updates:
        return Result(True, None)
    params.append(template_id)
    try:
        await db.execute(
            f"UPDATE homework_templates SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def update_homework_template_fields(
    template_id: int,
    *,
    title: str | None = None,
    description: str | None = None,
    answering_mode: str | None = None,
    max_attempts: int | None = None,
) -> Result:
    return await _with_db(
        _update_homework_template_fields,
        template_id,
        title=title,
        description=description,
        answering_mode=answering_mode,
        max_attempts=max_attempts,
    )


async def _add_homework_question(
    db: sql.Connection,
    template_id: int,
    question_type: str,
    text: str,
    correct_answer: str | None = None,
    points: float = 1.0,
) -> Result:
    try:
        rows = await db.execute_fetchall(
            'SELECT COALESCE(MAX(order_index), 0) FROM homework_questions WHERE assignment_id = ?',
            (template_id,),
        )
        order_index = (rows[0][0] or 0) + 1
        cursor = await db.execute(
            """
            INSERT INTO homework_questions (
                assignment_id, question_type, text, correct_answer, points, order_index
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (template_id, question_type, text, correct_answer, points, order_index),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None, cursor.lastrowid)


async def add_homework_question(
    template_id: int,
    question_type: str,
    text: str,
    correct_answer: str | None = None,
    points: float = 1.0,
) -> Result:
    return await _with_db(_add_homework_question, template_id, question_type, text, correct_answer, points)


async def _get_homework_question(db: sql.Connection, question_id: int) -> HomeworkQuestion | None:
    rows = await db.execute_fetchall(
        """
        SELECT id, assignment_id, question_type, text, correct_answer, points, order_index
        FROM homework_questions
        WHERE id = ?
        """,
        (question_id,),
    )
    if not rows:
        return None
    return HomeworkQuestion(*rows[0])


async def get_homework_question(question_id: int) -> HomeworkQuestion | None:
    return await _with_db(_get_homework_question, question_id)


async def _list_homework_questions(db: sql.Connection, template_id: int) -> list[HomeworkQuestion]:
    rows = await db.execute_fetchall(
        """
        SELECT id, assignment_id, question_type, text, correct_answer, points, order_index
        FROM homework_questions
        WHERE assignment_id = ?
        ORDER BY order_index
        """,
        (template_id,),
    )
    return [HomeworkQuestion(*row) for row in rows]


async def list_homework_questions(template_id: int) -> list[HomeworkQuestion]:
    return await _with_db(_list_homework_questions, template_id)


async def _update_homework_question_text(db: sql.Connection, question_id: int, text: str) -> Result:
    try:
        await db.execute(
            "UPDATE homework_questions SET text = ? WHERE id = ?",
            (text, question_id),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def update_homework_question_text(question_id: int, text: str) -> Result:
    return await _with_db(_update_homework_question_text, question_id, text)


async def _update_homework_question_answer(db: sql.Connection, question_id: int, correct_answer: str | None) -> Result:
    try:
        await db.execute(
            "UPDATE homework_questions SET correct_answer = ? WHERE id = ?",
            (correct_answer, question_id),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def update_homework_question_answer(question_id: int, correct_answer: str | None) -> Result:
    return await _with_db(_update_homework_question_answer, question_id, correct_answer)


async def _update_homework_question_points(db: sql.Connection, question_id: int, points: float) -> Result:
    try:
        await db.execute(
            "UPDATE homework_questions SET points = ? WHERE id = ?",
            (points, question_id),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def update_homework_question_points(question_id: int, points: float) -> Result:
    return await _with_db(_update_homework_question_points, question_id, points)


async def _delete_homework_question(db: sql.Connection, question_id: int) -> Result:
    try:
        rows = await db.execute_fetchall(
            'SELECT assignment_id, order_index FROM homework_questions WHERE id = ?',
            (question_id,),
        )
        if not rows:
            return Result(False, 'Question not found')
        assignment_id, order_index = rows[0]
        await db.execute('DELETE FROM homework_questions WHERE id = ?', (question_id,))
        await db.execute(
            """
            UPDATE homework_questions
            SET order_index = order_index - 1
            WHERE assignment_id = ? AND order_index > ?
            """,
            (assignment_id, order_index),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def delete_homework_question(question_id: int) -> Result:
    return await _with_db(_delete_homework_question, question_id)


async def _replace_homework_question_attachments(
    db: sql.Connection,
    question_id: int,
    attachments: list[tuple[str, str]],
) -> Result:
    try:
        await db.execute(
            'DELETE FROM homework_question_attachments WHERE question_id = ?',
            (question_id,),
        )
        await db.executemany(
            """
            INSERT INTO homework_question_attachments (
                question_id, file_id, file_type, position
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (question_id, file_id, file_type, position)
                for position, (file_id, file_type) in enumerate(attachments)
            ],
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def replace_homework_question_attachments(
    question_id: int,
    attachments: list[tuple[str, str]],
) -> Result:
    return await _with_db(_replace_homework_question_attachments, question_id, attachments)


async def _list_homework_question_attachments(
    db: sql.Connection,
    question_id: int,
) -> list[HomeworkQuestionAttachment]:
    rows = await db.execute_fetchall(
        """
        SELECT id, question_id, file_id, file_type, position
        FROM homework_question_attachments
        WHERE question_id = ?
        ORDER BY position
        """,
        (question_id,),
    )
    return [HomeworkQuestionAttachment(*row) for row in rows]


async def list_homework_question_attachments(question_id: int) -> list[HomeworkQuestionAttachment]:
    return await _with_db(_list_homework_question_attachments, question_id)


async def _replace_homework_question_options(
    db: sql.Connection,
    question_id: int,
    options: list[str],
) -> Result:
    try:
        await db.execute(
            'DELETE FROM homework_question_options WHERE question_id = ?',
            (question_id,),
        )
        await db.executemany(
            """
            INSERT INTO homework_question_options (
                question_id, option_text, is_correct, position
            ) VALUES (?, ?, 0, ?)
            """,
            [
                (question_id, option_text, position)
                for position, option_text in enumerate(options)
            ],
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def replace_homework_question_options(question_id: int, options: list[str]) -> Result:
    return await _with_db(_replace_homework_question_options, question_id, options)


async def _set_homework_question_correct_options(
    db: sql.Connection,
    question_id: int,
    correct_option_ids: list[int],
) -> Result:
    try:
        await db.execute(
            'UPDATE homework_question_options SET is_correct = 0 WHERE question_id = ?',
            (question_id,),
        )
        if correct_option_ids:
            await db.executemany(
                'UPDATE homework_question_options SET is_correct = 1 WHERE id = ?',
                [(option_id,) for option_id in correct_option_ids],
            )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def set_homework_question_correct_options(
    question_id: int,
    correct_option_ids: list[int],
) -> Result:
    return await _with_db(_set_homework_question_correct_options, question_id, correct_option_ids)


async def _list_homework_question_options(db: sql.Connection, question_id: int) -> list[HomeworkOption]:
    rows = await db.execute_fetchall(
        """
        SELECT id, question_id, option_text, is_correct, position
        FROM homework_question_options
        WHERE question_id = ?
        ORDER BY position
        """,
        (question_id,),
    )
    return [HomeworkOption(*row) for row in rows]


async def list_homework_question_options(question_id: int) -> list[HomeworkOption]:
    return await _with_db(_list_homework_question_options, question_id)


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
        await db.execute('UPDATE whitelist SET used = 1 WHERE tg_username = ?', (tg_username,))
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


async def _insert_registration_token(
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


async def insert_registration_token(tg_username: str, tg_id: int, token: str, grace_period: int = 600):
    """Store a registration token for a Telegram user.

    Args:
        tg_username (str): Telegram username.
        tg_id (int): Telegram user id.
        token (str): Generated token.
        grace_period (int, optional): Seconds until expiration. Defaults to 600.

    Returns:
        None
    """
    return await _with_db(_insert_registration_token, tg_username, tg_id, token, grace_period)


async def _insert_registrarion_token(
    db: sql.Connection,
    tg_username: str,
    tg_id: int,
    token: str,
    grace_period: int = 600,
):
    """Deprecated misspelled alias for `_insert_registration_token`."""
    return await _insert_registration_token(db, tg_username, tg_id, token, grace_period)


async def insert_registrarion_token(tg_username: str, tg_id: int, token: str, grace_period: int = 600):
    """Deprecated misspelled alias for `insert_registration_token`."""
    return await insert_registration_token(tg_username, tg_id, token, grace_period)


async def _validate_token_request(
    db: sql.Connection,
    tg_username: str,
    invite_code: str,
) -> Result:
    rows = tuple(
        await db.execute_fetchall(
            """
            SELECT used FROM whitelist WHERE (tg_username = ? AND invite_code = ?)
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
            return Result(False, f'Пользователь {tg_username} уже в белом списке')
        logging.log(level=logging.ERROR, msg=f'sqlite3.IntegrityError:{e}')
        return Result(False, str(e))
    return Result(True, None)


async def add_to_whitelist(tg_username: str, invite_code: str) -> Result:
    return await _with_db(_add_to_whitelist, tg_username, invite_code)


async def _assign_template_to_student(
    db: sql.Connection,
    template_id: int,
    student_tg_id: int,
    title: str,
    soft_deadline: str,
    hard_deadline: str,
) -> Result:
    try:
        template_rows = await db.execute_fetchall(
            'SELECT description FROM homework_templates WHERE id = ? AND is_published = 1',
            (template_id,),
        )
        if not template_rows:
            return Result(False, 'Шаблон задания не найден')
        description = template_rows[0][0] or ''
        cursor = await db.execute(
            """
            INSERT INTO homework_assignments (
                template_id, student_tg_id, title, text, soft_deadline, hard_deadline, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (template_id, student_tg_id, title, description, soft_deadline, hard_deadline, 'Не решено'),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None, cursor.lastrowid)


async def assign_template_to_student(
    template_id: int,
    student_tg_id: int,
    title: str,
    soft_deadline: str,
    hard_deadline: str,
) -> Result:
    return await _with_db(
        _assign_template_to_student,
        template_id,
        student_tg_id,
        title,
        soft_deadline,
        hard_deadline,
    )


async def _list_student_assignments_by_status(
    db: sql.Connection,
    student_tg_id: int,
    status: str,
) -> list[HomeworkAssignmentView]:
    rows = await db.execute_fetchall(
        """
        SELECT a.id, a.title, a.text, a.soft_deadline, a.hard_deadline, a.status,
               a.template_id, t.answering_mode, t.max_attempts
        FROM homework_assignments a
        LEFT JOIN homework_templates t ON a.template_id = t.id
        WHERE a.student_tg_id = ? AND a.status = ?
        ORDER BY a.created_at DESC
        """,
        (student_tg_id, status),
    )
    return [HomeworkAssignmentView(*row) for row in rows]


async def list_student_assignments_by_status(
    student_tg_id: int,
    status: str,
) -> list[HomeworkAssignmentView]:
    return await _with_db(_list_student_assignments_by_status, student_tg_id, status)


async def _list_student_assignments_by_statuses(
    db: sql.Connection,
    student_tg_id: int,
    statuses: list[str],
    limit: int,
    offset: int,
) -> list[HomeworkAssignmentView]:
    if not statuses:
        return []
    placeholders = ', '.join('?' for _ in statuses)
    rows = await db.execute_fetchall(
        f"""
        SELECT a.id, a.title, a.text, a.soft_deadline, a.hard_deadline, a.status,
               a.template_id, t.answering_mode, t.max_attempts
        FROM homework_assignments a
        LEFT JOIN homework_templates t ON a.template_id = t.id
        WHERE a.student_tg_id = ? AND a.status IN ({placeholders})
        ORDER BY a.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (student_tg_id, *statuses, limit, offset),
    )
    return [HomeworkAssignmentView(*row) for row in rows]


async def list_student_assignments_by_statuses(
    student_tg_id: int,
    statuses: list[str],
    limit: int,
    offset: int,
) -> list[HomeworkAssignmentView]:
    return await _with_db(
        _list_student_assignments_by_statuses,
        student_tg_id,
        statuses,
        limit,
        offset,
    )


async def _get_assignment_view(
    db: sql.Connection,
    assignment_id: int,
    student_tg_id: int | None = None,
) -> HomeworkAssignmentView | None:
    params: list[object] = [assignment_id]
    condition = ''
    if student_tg_id is not None:
        condition = 'AND a.student_tg_id = ?'
        params.append(student_tg_id)
    rows = await db.execute_fetchall(
        f"""
        SELECT a.id, a.title, a.text, a.soft_deadline, a.hard_deadline, a.status,
               a.template_id, t.answering_mode, t.max_attempts
        FROM homework_assignments a
        LEFT JOIN homework_templates t ON a.template_id = t.id
        WHERE a.id = ? {condition}
        """,
        tuple(params),
    )
    if not rows:
        return None
    return HomeworkAssignmentView(*rows[0])


async def get_assignment_view(assignment_id: int, student_tg_id: int | None = None) -> HomeworkAssignmentView | None:
    return await _with_db(_get_assignment_view, assignment_id, student_tg_id)


async def _get_next_unanswered_question(
    db: sql.Connection,
    assignment_id: int,
    student_tg_id: int,
) -> HomeworkQuestion | None:
    rows = await db.execute_fetchall(
        """
        SELECT q.id, q.assignment_id, q.question_type, q.text, q.correct_answer, q.points, q.order_index
        FROM homework_questions q
        LEFT JOIN (
            SELECT question_id, COUNT(*) as cnt
            FROM homework_assignment_attempts
            WHERE assignment_id = ? AND student_tg_id = ?
            GROUP BY question_id
        ) a ON a.question_id = q.id
        WHERE q.assignment_id = (
            SELECT template_id FROM homework_assignments WHERE id = ?
        )
          AND (a.cnt IS NULL OR a.cnt = 0)
        ORDER BY q.order_index
        LIMIT 1
        """,
        (assignment_id, student_tg_id, assignment_id),
    )
    if not rows:
        return None
    return HomeworkQuestion(*rows[0])


async def get_next_unanswered_question(assignment_id: int, student_tg_id: int) -> HomeworkQuestion | None:
    return await _with_db(_get_next_unanswered_question, assignment_id, student_tg_id)


async def _get_attempt_count(
    db: sql.Connection,
    assignment_id: int,
    question_id: int,
    student_tg_id: int,
) -> int:
    rows = await db.execute_fetchall(
        """
        SELECT COUNT(*)
        FROM homework_assignment_attempts
        WHERE assignment_id = ? AND question_id = ? AND student_tg_id = ?
        """,
        (assignment_id, question_id, student_tg_id),
    )
    return int(rows[0][0]) if rows else 0


async def get_attempt_count(assignment_id: int, question_id: int, student_tg_id: int) -> int:
    return await _with_db(_get_attempt_count, assignment_id, question_id, student_tg_id)


async def _get_latest_attempt_for_question(
    db: sql.Connection,
    assignment_id: int,
    question_id: int,
    student_tg_id: int,
) -> HomeworkAttempt | None:
    rows = await db.execute_fetchall(
        """
        SELECT id, answer_text, is_correct, score, attempt_index
        FROM homework_assignment_attempts
        WHERE assignment_id = ? AND question_id = ? AND student_tg_id = ?
        ORDER BY attempt_index DESC
        LIMIT 1
        """,
        (assignment_id, question_id, student_tg_id),
    )
    if not rows:
        return None
    return HomeworkAttempt(*rows[0])


async def get_latest_attempt_for_question(
    assignment_id: int,
    question_id: int,
    student_tg_id: int,
) -> HomeworkAttempt | None:
    return await _with_db(_get_latest_attempt_for_question, assignment_id, question_id, student_tg_id)


async def _list_attempt_attachments(
    db: sql.Connection,
    attempt_id: int,
) -> list[HomeworkAttemptAttachment]:
    rows = await db.execute_fetchall(
        """
        SELECT id, attempt_id, file_id, file_type, position
        FROM homework_attempt_attachments
        WHERE attempt_id = ?
        ORDER BY position
        """,
        (attempt_id,),
    )
    return [HomeworkAttemptAttachment(*row) for row in rows]


async def list_attempt_attachments(attempt_id: int) -> list[HomeworkAttemptAttachment]:
    return await _with_db(_list_attempt_attachments, attempt_id)


async def _list_attempt_option_texts(
    db: sql.Connection,
    attempt_id: int,
) -> list[str]:
    rows = await db.execute_fetchall(
        """
        SELECT o.option_text
        FROM homework_attempt_options ao
        JOIN homework_question_options o ON o.id = ao.option_id
        WHERE ao.attempt_id = ?
        ORDER BY o.position
        """,
        (attempt_id,),
    )
    return [row[0] for row in rows]


async def list_attempt_option_texts(attempt_id: int) -> list[str]:
    return await _with_db(_list_attempt_option_texts, attempt_id)


async def _get_assignment_max_attempt_index(
    db: sql.Connection,
    assignment_id: int,
    student_tg_id: int,
) -> int:
    rows = await db.execute_fetchall(
        """
        SELECT COALESCE(MAX(attempt_index), 0)
        FROM homework_assignment_attempts
        WHERE assignment_id = ? AND student_tg_id = ?
        """,
        (assignment_id, student_tg_id),
    )
    return int(rows[0][0]) if rows else 0


async def get_assignment_max_attempt_index(assignment_id: int, student_tg_id: int) -> int:
    return await _with_db(_get_assignment_max_attempt_index, assignment_id, student_tg_id)


async def _list_assignment_max_attempts(
    db: sql.Connection,
    student_tg_id: int,
    assignment_ids: list[int],
) -> dict[int, int]:
    if not assignment_ids:
        return {}
    placeholders = ', '.join('?' for _ in assignment_ids)
    rows = await db.execute_fetchall(
        f"""
        SELECT assignment_id, COALESCE(MAX(attempt_index), 0)
        FROM homework_assignment_attempts
        WHERE student_tg_id = ? AND assignment_id IN ({placeholders})
        GROUP BY assignment_id
        """,
        (student_tg_id, *assignment_ids),
    )
    return {row[0]: int(row[1]) for row in rows}


async def list_assignment_max_attempts(
    student_tg_id: int,
    assignment_ids: list[int],
) -> dict[int, int]:
    return await _with_db(_list_assignment_max_attempts, student_tg_id, assignment_ids)


async def _record_assignment_attempt(
    db: sql.Connection,
    assignment_id: int,
    question_id: int,
    student_tg_id: int,
    attempt_index: int,
    answer_text: str | None,
    is_correct: int | None,
    score: float | None,
    attachments: list[tuple[str, str]] | None = None,
    selected_option_ids: list[int] | None = None,
) -> Result:
    try:
        cursor = await db.execute(
            """
            INSERT INTO homework_assignment_attempts (
                assignment_id, question_id, student_tg_id, attempt_index, answer_text, is_correct, score
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (assignment_id, question_id, student_tg_id, attempt_index, answer_text, is_correct, score),
        )
        attempt_id = cursor.lastrowid
        if attachments:
            await db.executemany(
                """
                INSERT INTO homework_attempt_attachments (
                    attempt_id, file_id, file_type, position
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (attempt_id, file_id, file_type, position)
                    for position, (file_id, file_type) in enumerate(attachments)
                ],
            )
        if selected_option_ids:
            await db.executemany(
                """
                INSERT INTO homework_attempt_options (attempt_id, option_id)
                VALUES (?, ?)
                """,
                [(attempt_id, option_id) for option_id in selected_option_ids],
            )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None, attempt_id)


async def record_assignment_attempt(
    assignment_id: int,
    question_id: int,
    student_tg_id: int,
    attempt_index: int,
    answer_text: str | None,
    is_correct: int | None,
    score: float | None,
    attachments: list[tuple[str, str]] | None = None,
    selected_option_ids: list[int] | None = None,
) -> Result:
    return await _with_db(
        _record_assignment_attempt,
        assignment_id,
        question_id,
        student_tg_id,
        attempt_index,
        answer_text,
        is_correct,
        score,
        attachments,
        selected_option_ids,
    )


async def _get_assignment_question_counts(
    db: sql.Connection,
    assignment_id: int,
    student_tg_id: int,
) -> tuple[int, int]:
    rows = await db.execute_fetchall(
        """
        SELECT COUNT(*) FROM homework_questions
        WHERE assignment_id = (SELECT template_id FROM homework_assignments WHERE id = ?)
        """,
        (assignment_id,),
    )
    total = int(rows[0][0]) if rows else 0
    answered_rows = await db.execute_fetchall(
        """
        SELECT COUNT(DISTINCT question_id)
        FROM homework_assignment_attempts
        WHERE assignment_id = ? AND student_tg_id = ?
        """,
        (assignment_id, student_tg_id),
    )
    answered = int(answered_rows[0][0]) if answered_rows else 0
    return total, answered


async def get_assignment_question_counts(assignment_id: int, student_tg_id: int) -> tuple[int, int]:
    return await _with_db(_get_assignment_question_counts, assignment_id, student_tg_id)


async def _set_assignment_status(db: sql.Connection, assignment_id: int, status: str) -> Result:
    try:
        await db.execute(
            "UPDATE homework_assignments SET status = ? WHERE id = ?",
            (status, assignment_id),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def set_assignment_status(assignment_id: int, status: str) -> Result:
    return await _with_db(_set_assignment_status, assignment_id, status)


async def _save_homework(
    db: sql.Connection,
    student_tg_id: int,
    title: str,
    text: str,
    soft_deadline: str,
    hard_deadline: str,
    attachments: list[tuple[str, str]] | None = None,
) -> Result:
    try:
        cursor = await db.execute(
            """
            INSERT INTO homework_assignments (
                student_tg_id, title, text, soft_deadline, hard_deadline, status
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_tg_id, title, text, soft_deadline, hard_deadline, 'Не решено'),
        )
        assignment_id = cursor.lastrowid
        if attachments:
            await db.executemany(
                """
                INSERT INTO homework_assignment_attachments (
                    assignment_id, file_id, file_type, position
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (assignment_id, file_id, file_type, position)
                    for position, (file_id, file_type) in enumerate(attachments)
                ],
            )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None, assignment_id)


async def save_homework(
    student_tg_id: int,
    title: str,
    text: str,
    soft_deadline: str,
    hard_deadline: str,
    attachments: list[tuple[str, str]] | None = None,
) -> Result:
    return await _with_db(_save_homework, student_tg_id, title, text, soft_deadline, hard_deadline, attachments)


async def _save_homework_submission(
    db: sql.Connection,
    assignment_id: int,
    student_tg_id: int,
    attachments: list[tuple[str, str]],
    text: str | None = None,
) -> Result:
    try:
        cursor = await db.execute(
            """
            INSERT INTO homework_submissions (assignment_id, student_tg_id, text)
            VALUES (?, ?, ?)
            """,
            (assignment_id, student_tg_id, text),
        )
        submission_id = cursor.lastrowid
        await db.executemany(
            """
            INSERT INTO homework_submission_attachments (
                submission_id, file_id, file_type, position
            ) VALUES (?, ?, ?, ?)
            """,
            [
                (submission_id, file_id, file_type, position)
                for position, (file_id, file_type) in enumerate(attachments)
            ],
        )
        await db.execute(
            "UPDATE homework_assignments SET status = ? WHERE id = ?",
            ('На проверке', assignment_id),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None, submission_id)


async def save_homework_submission(
    assignment_id: int,
    student_tg_id: int,
    attachments: list[tuple[str, str]],
    text: str | None = None,
) -> Result:
    return await _with_db(_save_homework_submission, assignment_id, student_tg_id, attachments, text)


async def get_tg_user_id_by_tg_username(tg_username: str) -> Result:
    return await _with_db(_get_tg_user_id_by_tg_username, tg_username)


async def _get_tg_user_id_by_tg_username(db: sql.Connection, tg_username: str) -> Result:
    try:
        rows = await db.execute_fetchall(
            'SELECT tg_id FROM users WHERE tg_username = ?',
            (tg_username,),
        )
        if not rows:
            return Result(False, 'User not found')
        return Result(True, None, rows[0][0])
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))


async def get_tg_user_id_by_username(username: str) -> Result:
    return await _with_db(_get_tg_user_id_by_username, username)


async def _get_tg_user_id_by_username(db: sql.Connection, username: str) -> Result:
    try:
        rows = await db.execute_fetchall(
            'SELECT tg_id FROM users WHERE username = ?',
            (username,),
        )
        if not rows:
            return Result(False, 'User not found')
        return Result(True, None, rows[0][0])
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))


async def _upsert_account_provisioning(
    db: sql.Connection,
    username: str,
    status: str,
    error: str | None = None,
) -> Result:
    try:
        await db.execute(
            """
            INSERT INTO account_provisioning (username, status, error)
            VALUES (?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                status = excluded.status,
                error = excluded.error,
                updated_at = datetime('now')
            """,
            (username, status, error),
        )
        await db.commit()
    except Exception as exc:
        logging.log(level=logging.ERROR, msg=exc)
        return Result(False, str(exc))
    return Result(True, None)


async def upsert_account_provisioning(
    username: str,
    status: str,
    error: str | None = None,
) -> Result:
    return await _with_db(_upsert_account_provisioning, username, status, error)


async def _get_account_provisioning(db: sql.Connection, username: str) -> ProvisioningStatus | None:
    rows = await db.execute_fetchall(
        """
        SELECT username, status, error, created_at, updated_at
        FROM account_provisioning
        WHERE username = ?
        """,
        (username,),
    )
    if not rows:
        return None
    return ProvisioningStatus(*rows[0])


async def get_account_provisioning(username: str) -> ProvisioningStatus | None:
    return await _with_db(_get_account_provisioning, username)
