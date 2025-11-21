students-crm
============

A Telegram-driven invite workflow for managing student registrations. The `students_bot` issues invite codes and short-lived registration tokens via Telegram, while the FastAPI web form (`webform`) collects usernames/passwords and finalizes the account in SQLite. This is an early version and the architecture/API will likely evolve.

## Prerequisites

- Python 3.11+
- SQLite (bundled with Python)
- Telegram bot token and administrator Telegram user ID
- Environment variables (place them in `.env` for convenience):
  - `API_KEY` – Telegram bot token
  - `ADMIN_ID` – Telegram user ID allowed to run admin commands
  - `DB_PATH` – path to the SQLite database file (e.g., `students.db`)
  - `REGISTRATION_URL_BASE` – base URL of the FastAPI `/register` endpoint (e.g., `https://example.com/register`)

## Setup & Run with uv

1. Install uv (https://github.com/astral-sh/uv) if you have not already.
2. From the project root run:
   ```bash
   uv python install 3.11
   uv sync
   ```
3. Start the Telegram bot:
   ```bash
   uv run python students_bot/main.py
   ```
4. In another terminal, launch the FastAPI web form (served by uvicorn via FastAPI's standard extra):
   ```bash
   uv run uvicorn webform.main:app --host 0.0.0.0 --port 8000
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
3. Start the Telegram bot:
   ```bash
   python students_bot/main.py
   ```
4. Start the FastAPI web form in a separate shell:
   ```bash
   uvicorn webform.main:app --host 0.0.0.0 --port 8000
   ```

With both processes running, admins can whitelist users via Telegram, users can request tokens through the bot, and then finish registration through the `/register` web form.
