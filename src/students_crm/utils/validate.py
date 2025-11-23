import re

USERNAME_RE = re.compile('^[a-zA-Z][a-zA-Z0-9_]{2,31}$')


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
    # TODO: add security validation
    if len(password) < 6:
        return 'Пароль должен содержать минимум 6 символов.'
    return None
