students-crm
============

A Telegram-driven invite workflow for managing student registrations. The `students_bot` issues invite codes and short-lived registration tokens via Telegram, while the FastAPI web form (`webform`) collects usernames/passwords and finalizes the account in SQLite. This is an early version and the architecture/API will likely evolve.

## Prerequisites

- Python 3.11+
- SQLite (bundled with Python)
- Telegram bot token and administrator Telegram user ID
- Environment variables (place them in `.env.local` for local runs or `.env.docker` for Docker):
  - `API_KEY` – Telegram bot token
  - `ADMIN_ID` – Telegram user ID allowed to run admin commands
  - `DB_PATH` – path to the SQLite database file (e.g., `students.db`)
  - `REGISTRATION_URL_BASE` – base URL of the FastAPI `/register` endpoint (e.g., `https://example.com/register`)
  - `TEACHER_USERNAME` – Linux account that should have access to every student home (default: `teacher`)
  - `STUDENTS_GROUP` – shared Unix group for students (default: `students`)
  - `STUDENTS_HOME_BASE` – base path that will contain student home directories (default: `/home`)
  - `STUDENT_DEFAULT_SHELL` – shell assigned to student accounts (default: `/bin/bash`)
  - `DEBUG` – set to `true`/`false` to toggle debug behavior (default: `false`)

## Setup & Run with uv

1. Install uv (https://github.com/astral-sh/uv) if you have not already.
2. From the project root run:
   ```bash
   uv python install 3.11
   uv sync
   ```
3. Start the Telegram bot:
   ```bash
   uv run --env-file .env.local python -m students_crm.students_bot.main
   ```
4. In another terminal, launch the FastAPI web form (served by uvicorn via FastAPI's standard extra):
   ```bash
   uv run --env-file .env.local uvicorn students_crm.webform.main:app --host 0.0.0.0 --port 8000
   ```

## Debug vs Release

- Release mode (default): `DEBUG` is false unless explicitly enabled. Keep this default for production and deployment.
- Debug mode: set `DEBUG=1` or `DEBUG=true` in `.env.local` only for local development. This enables FastAPI debug mode and lets the admin test the student `/homework` flow by sending `/homework` with no args. Assignment still uses `/homework <username>`.

Examples:

```bash
DEBUG=1 uv run --env-file .env.local python -m students_crm.students_bot.main
DEBUG=1 uv run --env-file .env.local uvicorn students_crm.webform.main:app --host 0.0.0.0 --port 8000
```

```bash
DEBUG=0 uv run --env-file .env.local python -m students_crm.students_bot.main
DEBUG=0 uv run --env-file .env.local uvicorn students_crm.webform.main:app --host 0.0.0.0 --port 8000
```

## Database migrations

Migrations run automatically when the bot starts. You can also apply them manually:

```bash
uv run --env-file .env.local python -m students_crm.db.migrate
```

```bash
docker compose run --rm bot uv run python -m students_crm.db.migrate
```

## Setup & Run with pip

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. Load environment variables:
   ```bash
   set -a
   source .env.local
   set +a
   ```
4. Start the Telegram bot:
   ```bash
   python -m students_crm.students_bot.main
   ```
5. Start the FastAPI web form in a separate shell:
   ```bash
   uvicorn students_crm.webform.main:app --host 0.0.0.0 --port 8000
   ```

## Run with Docker

1. Ensure `.env.docker` has the Docker paths (notably `DB_PATH=/app/db/students.db`).
2. Build and run:
   ```bash
   docker compose up --build
   ```

See `docs/docker.md` for Docker usage and DB inspection. See `docs/security.md` for the current hardening checklist and known security follow-ups.

With both processes running, admins can whitelist users via Telegram, users can request tokens through the bot, and then finish registration through the `/register` web form.
