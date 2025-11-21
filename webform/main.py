import os
import sys
from typing import Any

import aiosqlite
import sqlite3
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from constants import *
from db.db import register_user
from security import hash_password
from validate import validate_password, validate_username

app = FastAPI()
templates = Jinja2Templates(directory='webform/templates')


@app.get('/register', response_class=HTMLResponse)
async def register_get(request: Request, token: str) -> Any:
    '''Render the registration form with a hidden token.

    Args:
        request (Request): Incoming HTTP request.
        token (str): Registration token.

    Returns:
        TemplateResponse: HTML response for the registration form.
    '''
    return templates.TemplateResponse(
        'register.html',
        {
            'request': request,
            'error': None,
            'success': False,
            'token': token,
        },
    )


@app.post('/register', response_class=HTMLResponse)
async def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
    token: str = Form(...),
):
    '''Process registration submissions and persist new users.

    Args:
        request (Request): Incoming HTTP request.
        username (str): Desired username.
        password (str): Password entry.
        password2 (str): Password confirmation.
        token (str): Registration token.

    Returns:
        TemplateResponse: HTML response describing the outcome.
    '''
    username = username.strip()

    error = None
    success = False

    if not all((username, password, password2, token)):
        error = 'Пожалуйста, заполните все поля.'
    elif password != password2:
        error = 'Пароли не совпадают.'
    elif username_error := validate_username(username):
        error = username_error
    elif password_error := validate_password(password):
        error = password_error
    else:
        password_hash = hash_password(password)
        res = await register_user(username, password_hash, token)
        error = res.message
        success = res.ok

    return templates.TemplateResponse(
        'register.html',
        {
            'request': request,
            'error': error,
            'success': success,
            'token': token,
        },
    )
