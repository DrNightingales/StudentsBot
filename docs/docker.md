# Docker usage

This project ships with a persistent SQLite volume (`db-data`). A browser-based DB inspector is available behind a debug-only Docker Compose profile.

## Prereqs

- Docker and Docker Compose
- `.env.docker` with `DB_PATH=/app/db/students.db`

## Build and run

```bash
docker compose up --build
```

`DEBUG` defaults to false. Keep it disabled for production and only set `DEBUG=true` in local development env files.

## Run migrations

Migrations run automatically when the bot starts. To run them manually:

```bash
docker compose run --rm bot uv run python -m students_crm.db.migrate
```

## Inspect the DB

The DB inspector runs in a separate container and mounts the same `db-data` volume. It is behind a reverse proxy with Basic Auth, bound to localhost, and only starts when the `debug` profile is enabled.

Add these variables to `.env.docker`:

```bash
DB_INSPECTOR_USER=admin
DB_INSPECTOR_PASSWORD_HASH=$2a$12$example_bcrypt_hash_here
```

To generate a bcrypt hash with Caddy:

```bash
docker run --rm caddy:2 caddy hash-password --plaintext "your-password"
```

```bash
docker compose --profile debug up db-proxy
```

Open `http://localhost:8081` and log in with the Basic Auth credentials.

## Stop containers

```bash
docker compose down
```

To delete the persistent DB volume:

```bash
docker compose down -v
```
