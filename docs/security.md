# Security Notes

This project handles Telegram invite tokens, password hashes, and optional Linux account provisioning. Treat the bot, web form, SQLite DB, and provisioning queue as security-sensitive components.

## Immediate Checklist

- Keep `.env*` files out of git and Docker images. Use `.env.example` files for documentation only.
- Rotate Telegram bot tokens and DB inspector credentials if they were ever committed, shared, or copied into built images.
- Keep `DEBUG=false` by default. Enable debug only for local development.
- Serve the registration form only over HTTPS in production.
- Keep DB inspection disabled unless you are intentionally running local debug tooling.
- Run the account provisioner with the least privileges practical for your host. Do not expose the queue directory to untrusted users.

## Current Hardening

- Local env files, database files, logs, caches, and editor state are ignored by git and Docker builds.
- Docker commands rely on Compose/runtime environment injection instead of loading env files inside the image command.
- The web container uses `uvicorn` instead of the FastAPI development server.
- `DEBUG` defaults to false.

## Known Follow-Ups

- Restrict registration token delivery to private Telegram chats.
- Validate registration tokens before expensive password hashing.
- Add no-referrer/no-store headers to registration pages.
- Strengthen password validation for Linux account creation and bcrypt limits.
- Store registration token hashes instead of plaintext token values.
- Move rate limiting to a shared backend if running multiple web/bot processes.
- Restrict trusted proxy headers to known proxy IPs before enabling `TRUST_PROXY_HEADERS`.
- Consider a dedicated, narrowly scoped provisioning service instead of sharing credentials or sudo access with web/bot runtimes.
- Return generic registration errors to users while logging detailed database exceptions server-side.
