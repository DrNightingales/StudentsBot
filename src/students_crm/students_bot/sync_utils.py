import base64
import secrets

ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def generate_invite_code() -> str:
    '''Generate an invite code in the form ABCD-EFGH.

    Returns:
        str: Formatted invite code.
    '''
    raw = ''.join(secrets.choice(ALPHABET) for _ in range(8))
    return raw[:4] + '-' + raw[4:]


def generate_token_fixed(n_bytes: int = 12) -> str:
    '''Generate a URL-safe token from secure random bytes.

    Args:
        n_bytes (int, optional): Number of random bytes. Defaults to 12.

    Returns:
        str: Encoded token.
    '''
    return base64.urlsafe_b64encode(secrets.token_bytes(n_bytes)).rstrip(b'=').decode()
