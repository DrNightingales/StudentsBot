from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from asyncio import to_thread

from students_crm.utilities.security import hash_password
from students_crm.utilities.validate import validate_password, validate_username
from students_crm.db.db import register_user
from students_crm.utilities.system_users import create_student_account
from students_crm.utilities.constants import (
    TEACHER_USERNAME,
    DEBUG,
    STUDENTS_GROUP,
    STUDENT_DEFAULT_SHELL,
    STUDENTS_HOME_BASE,
)

app = FastAPI(debug=DEBUG)
templates = Jinja2Templates(directory='webform/templates')

@app.get('/register', response_class=HTMLResponse)
async def register_get(request: Request, token: str) -> Any:
    """Render the registration form with a hidden token.

    Args:
        request (Request): Incoming HTTP request.
        token (str): Registration token.

    Returns:
        TemplateResponse: HTML response for the registration form.
    """
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
        if success:
            await to_thread(
                create_student_account,
                username,
                password,
                teacher_username=TEACHER_USERNAME,
                students_group=STUDENTS_GROUP,
                home_base=STUDENTS_HOME_BASE,
                default_shell=STUDENT_DEFAULT_SHELL,
            )

    return templates.TemplateResponse(
        'register.html',
        {
            'request': request,
            'error': error,
            'success': success,
            'token': token,
        },
    )
