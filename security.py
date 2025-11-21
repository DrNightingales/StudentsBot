import bcrypt


def hash_password(password: str) -> str:
    '''Hash a password using bcrypt.

    Args:
        password (str): Plaintext password.

    Returns:
        str: Hashed password.
    '''
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def verify_password(plain_password: str, hashed: str) -> bool:
    '''Verify a password against its hash.

    Args:
        plain_password (str): User supplied plaintext password.
        hashed (str): Stored bcrypt hash.

    Returns:
        bool: True if the password matches, False otherwise.
    '''
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed.encode('utf-8'),
    )
