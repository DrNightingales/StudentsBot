from typing import Any
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from asyncio import to_thread
import logging

from students_crm.utils.security import hash_password
from students_crm.utils.validate import validate_password, validate_username
from students_crm.db.routines import register_user, upsert_account_provisioning, validate_token
from students_crm.provisioner import enqueue_account_request
from students_crm.utils.constants import (
    DEBUG,
    PROVISIONING_STATUS_FAILED,
    PROVISIONING_STATUS_QUEUED,
    REGISTRATION_RATE_LIMIT_COUNT,
    REGISTRATION_RATE_LIMIT_WINDOW,
    TRUST_PROXY_HEADERS,
)
from students_crm.utils.rate_limit import RateLimiter

app = FastAPI(debug=DEBUG)
templates = Jinja2Templates(directory=str(Path(__file__).with_name('templates')))
registration_limiter = RateLimiter(REGISTRATION_RATE_LIMIT_COUNT, REGISTRATION_RATE_LIMIT_WINDOW)


@app.middleware('http')
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault('Referrer-Policy', 'no-referrer')
    response.headers.setdefault('Cache-Control', 'no-store')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    return response


def _client_ip(request: Request) -> str:
    if TRUST_PROXY_HEADERS:
        forwarded = request.headers.get('x-forwarded-for')
        if forwarded:
            return forwarded.split(',')[0].strip()
        real_ip = request.headers.get('x-real-ip')
        if real_ip:
            return real_ip.strip()
    if request.client:
        return request.client.host
    return 'unknown'


def _render_registration(
    request: Request,
    *,
    token: str,
    error: str | None = None,
    success: bool = False,
):
    return templates.TemplateResponse(
        'register.html',
        {
            'request': request,
            'error': error,
            'success': success,
            'token': '' if success else token,
        },
    )


@app.get('/register', response_class=HTMLResponse)
async def register_get(request: Request, token: str) -> Any:
    """Render the registration form with a hidden token.

    Args:
        request (Request): Incoming HTTP request.
        token (str): Registration token.

    Returns:
        TemplateResponse: HTML response for the registration form.
    """
    if not await validate_token(token):
        return _render_registration(
            request,
            token='',
            error='Ваш токен не действителен, используйте команду /register повторно.',
        )
    return _render_registration(request, token=token)


@app.post('/register', response_class=HTMLResponse)
async def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    token: str = Form(...),
):
    """Process registration submissions and persist new users.

    Args:
        request (Request): Incoming HTTP, init_db request.
        username (str): Desired username.
        password (str): Password entry.
        password2 (str): Password confirmation.
        token (str): Registration token.

    Returns:
        TemplateResponse: HTML response describing the outcome.
    """
    username = username.strip()

    error = None
    success = False

    client_ip = _client_ip(request)
    if not registration_limiter.allow(client_ip):
        error = 'Слишком много попыток. Попробуйте позже.'
        return _render_registration(request, token=token, error=error, success=success)

    if not all((username, password, password2, token)):
        error = 'Пожалуйста, заполните все поля.'
    elif password != password2:
        error = 'Пароли не совпадают.'
    elif username_error := validate_username(username):
        error = username_error
    elif password_error := validate_password(password):
        error = password_error
    elif not await validate_token(token):
        error = 'Ваш токен не действителен, используйте команду /register повторно.'
    else:
        password_hash = hash_password(password)
        res = await register_user(username, password_hash, token)
        error = res.message
        success = res.ok
        if success:
            await upsert_account_provisioning(username, PROVISIONING_STATUS_QUEUED, None)
            try:
                await to_thread(
                    enqueue_account_request,
                    username,
                    password_hash,
                )
            except Exception:
                logging.exception('Failed to enqueue account request for %s', username)
                error = 'Регистрация завершена, но не удалось поставить создание учетной записи в очередь.'
                await upsert_account_provisioning(username, PROVISIONING_STATUS_FAILED, error)

    return _render_registration(request, token=token, error=error, success=success)
