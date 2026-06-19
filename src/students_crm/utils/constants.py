from dotenv import load_dotenv
from os import environ

load_dotenv()


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {'1', 'true', 'yes', 'on'}:
        return True
    if normalized in {'0', 'false', 'no', 'off'}:
        return False
    return default


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    cleaned = value.strip()
    if not cleaned:
        return default
    try:
        return int(cleaned)
    except ValueError:
        return default


API_KEY = environ['API_KEY']
ADMIN_ID = int(environ['ADMIN_ID'])
DB_PATH = environ['DB_PATH']
REGISTRATION_URL_BASE = environ['REGISTRATION_URL_BASE']
TEACHER_USERNAME = environ['TEACHER_USERNAME']
STUDENTS_GROUP = environ.get('STUDENTS_GROUP', 'students')
STUDENT_DEFAULT_SHELL = environ.get('STUDENT_DEFAULT_SHELL', '/bin/bash')
STUDENTS_HOME_BASE = environ.get('STUDENTS_HOME_BASE', '/home')
DEBUG = _parse_bool(environ.get('DEBUG'), False)
REGISTRATION_RATE_LIMIT_COUNT = _parse_int(environ.get('REGISTRATION_RATE_LIMIT_COUNT'), 5)
REGISTRATION_RATE_LIMIT_WINDOW = _parse_int(environ.get('REGISTRATION_RATE_LIMIT_WINDOW'), 60)
BOT_TOKEN_RATE_LIMIT_COUNT = _parse_int(environ.get('BOT_TOKEN_RATE_LIMIT_COUNT'), 3)
BOT_TOKEN_RATE_LIMIT_WINDOW = _parse_int(environ.get('BOT_TOKEN_RATE_LIMIT_WINDOW'), 300)
TRUST_PROXY_HEADERS = _parse_bool(environ.get('TRUST_PROXY_HEADERS'), False)
