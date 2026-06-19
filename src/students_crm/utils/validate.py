import re

USERNAME_RE = re.compile('^[a-zA-Z][a-zA-Z0-9_]{2,31}$')
PASSWORD_MIN_LENGTH = 10
BCRYPT_MAX_PASSWORD_BYTES = 72


def validate_username(username: str) -> str | None:
    """Validate a username against the allowed pattern.

    Args:
        username (str): Submitted username.

    Returns:
        str | None: Error message if invalid, otherwise None.
    """
    if not USERNAME_RE.match(username):
        return (
            'Имя пользователя должно состоять только из латинских букв, цифр и знака _.\n'
            'Имя пользователя должно начинаться с буквы и быть длиной 3-32 символа.'
        )
    return None


def validate_password(password: str) -> str | None:
    """Validate that the supplied password meets minimum requirements.

    Args:
        password (str): Submitted password.

    Returns:
        str | None: Error message if invalid, otherwise None.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f'Пароль должен содержать минимум {PASSWORD_MIN_LENGTH} символов.'
    if len(password.encode('utf-8')) > BCRYPT_MAX_PASSWORD_BYTES:
        return f'Пароль должен быть не длиннее {BCRYPT_MAX_PASSWORD_BYTES} байт.'
    if not any(char.isdigit() for char in password):
        return 'Пароль должен содержать минимум одну цифру.'
    if not any(char.isupper() for char in password):
        return 'Пароль должен содержать минимум одну заглавную букву.'
    return None
