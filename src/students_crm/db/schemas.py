db_schemas = {
    'whitelist': """
             CREATE TABLE IF NOT EXISTS whitelist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tg_username TEXT UNIQUE NOT NULL,
                    invite_code TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
               """,
    'users': """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    tg_id INTEGER NOT NULL UNIQUE,
                    tg_username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                );
                """,
    'registration_tokens': """
                CREATE TABLE IF NOT EXISTS registration_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    tg_username TEXT NOT NULL,
                    tg_id INTEGER NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    used INTEGER NOT NULL DEFAULT 0
                );
                """,
    'account_provisioning': """
                CREATE TABLE IF NOT EXISTS account_provisioning (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL
                        CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
                    error TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """,
    'homework_templates': """
                CREATE TABLE IF NOT EXISTS homework_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    answering_mode TEXT NOT NULL DEFAULT 'FREE'
                        CHECK (answering_mode IN ('FREE', 'FIXED')),
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    is_published INTEGER NOT NULL DEFAULT 0,
                    created_by_tg_id INTEGER REFERENCES users(tg_id),
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """,
    'homework_questions': """
                CREATE TABLE IF NOT EXISTS homework_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL REFERENCES homework_templates(id) ON DELETE CASCADE,
                    question_type TEXT NOT NULL
                        CHECK (question_type IN ('open', 'short', 'mcq')),
                    text TEXT NOT NULL,
                    correct_answer TEXT,
                    points REAL NOT NULL DEFAULT 1,
                    order_index INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """,
    'homework_assignments': """
                CREATE TABLE IF NOT EXISTS homework_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER REFERENCES homework_templates(id),
                    student_tg_id INTEGER NOT NULL REFERENCES users(tg_id),
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    soft_deadline TEXT NOT NULL,   -- ISO-8601 datetime
                    hard_deadline TEXT NOT NULL,   -- ISO-8601 datetime
                    status TEXT NOT NULL DEFAULT 'Не решено'
                        CHECK (status IN ('Не решено', 'На проверке', 'Пройдено', 'Провалено')),
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """,
    'homework_question_attachments': """
                CREATE TABLE IF NOT EXISTS homework_question_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL REFERENCES homework_questions(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    position INTEGER NOT NULL
                );
                """,
    'homework_question_options': """
                CREATE TABLE IF NOT EXISTS homework_question_options (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question_id INTEGER NOT NULL REFERENCES homework_questions(id) ON DELETE CASCADE,
                    option_text TEXT NOT NULL,
                    is_correct INTEGER NOT NULL DEFAULT 0,
                    position INTEGER NOT NULL
                );
                """,
    'homework_assignment_attempts': """
                CREATE TABLE IF NOT EXISTS homework_assignment_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL REFERENCES homework_assignments(id) ON DELETE CASCADE,
                    question_id INTEGER NOT NULL REFERENCES homework_questions(id) ON DELETE CASCADE,
                    student_tg_id INTEGER NOT NULL REFERENCES users(tg_id),
                    attempt_index INTEGER NOT NULL,
                    answer_text TEXT,
                    is_correct INTEGER,
                    score REAL,
                    submitted_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """,
    'homework_attempt_attachments': """
                CREATE TABLE IF NOT EXISTS homework_attempt_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attempt_id INTEGER NOT NULL REFERENCES homework_assignment_attempts(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    position INTEGER NOT NULL
                );
                """,
    'homework_attempt_options': """
                CREATE TABLE IF NOT EXISTS homework_attempt_options (
                    attempt_id INTEGER NOT NULL REFERENCES homework_assignment_attempts(id) ON DELETE CASCADE,
                    option_id INTEGER NOT NULL REFERENCES homework_question_options(id) ON DELETE CASCADE,
                    PRIMARY KEY (attempt_id, option_id)
                );
                """,
    'homework_assignment_attachments': """
                CREATE TABLE IF NOT EXISTS homework_assignment_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL REFERENCES homework_assignments(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,   -- Telegram file_id
                    file_type TEXT NOT NULL,   -- 'photo', 'document', etc.
                    position INTEGER NOT NULL -- display order
                );
                """,
    'homework_submissions': """
                CREATE TABLE IF NOT EXISTS homework_submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    assignment_id INTEGER NOT NULL REFERENCES homework_assignments(id) ON DELETE CASCADE,
                    student_tg_id INTEGER NOT NULL REFERENCES users(tg_id),
                    text TEXT,
                    submitted_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """,
    'homework_submission_attachments': """
                CREATE TABLE IF NOT EXISTS homework_submission_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL REFERENCES homework_submissions(id) ON DELETE CASCADE,
                    file_id TEXT NOT NULL,   -- Telegram file_id
                    file_type TEXT NOT NULL,   -- 'photo', 'document', etc.
                    position INTEGER NOT NULL -- display order
                );
                """,

}
