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
}
