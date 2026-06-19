import argparse
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from uuid import uuid4

from students_crm.utils.constants import (
    ACCOUNT_REQUESTS_DIR,
    PROVISIONING_STATUS_COMPLETED,
    PROVISIONING_STATUS_FAILED,
    PROVISIONING_STATUS_PROCESSING,
    STUDENT_DEFAULT_SHELL,
    STUDENTS_GROUP,
    STUDENTS_HOME_BASE,
    TEACHER_USERNAME,
)
from students_crm.db.routines import upsert_account_provisioning
from students_crm.utils.system_users import create_student_account, user_exists
from students_crm.utils.validate import validate_username


REQUEST_SUFFIX = '.json'


@dataclass(frozen=True)
class AccountRequest:
    username: str
    password_hash: str
    requested_at: str
    version: int = 1


def _ensure_queue_dir(queue_path: Path) -> None:
    queue_path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(queue_path, 0o700)
    except OSError:
        logging.warning('Queue directory permissions could not be tightened: %s', queue_path)


def _queue_dir(queue_dir: str | None = None) -> Path:
    queue_path = Path(queue_dir or ACCOUNT_REQUESTS_DIR)
    _ensure_queue_dir(queue_path)
    return queue_path


def _write_json_secure(path: Path, payload: dict) -> None:
    _ensure_queue_dir(path.parent)
    tmp_path = path.with_name(f'.{path.name}.tmp')
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=True)
            handle.write('\n')
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def enqueue_account_request(
    username: str,
    password_hash: str,
    *,
    queue_dir: str | None = None,
) -> Path:
    username_error = validate_username(username)
    if username_error:
        raise ValueError(username_error)
    if not password_hash or not password_hash.startswith('$2'):
        raise ValueError('Неверный формат хэша пароля.')
    request = AccountRequest(
        username=username,
        password_hash=password_hash,
        requested_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
    )
    payload = {
        'version': request.version,
        'username': request.username,
        'password_hash': request.password_hash,
        'requested_at': request.requested_at,
    }
    queue_path = _queue_dir(queue_dir)
    filename = f'{int(time.time())}_{uuid4().hex}{REQUEST_SUFFIX}'
    request_path = queue_path / filename
    _write_json_secure(request_path, payload)
    return request_path


def _iter_requests(queue_path: Path) -> list[Path]:
    if not queue_path.exists():
        return []
    return sorted(
        [
            item
            for item in queue_path.iterdir()
            if not item.is_symlink() and item.is_file() and item.name.endswith(REQUEST_SUFFIX)
        ]
    )


def _claim_request(path: Path) -> Path | None:
    processing_path = path.with_name(f'{path.name}.processing')
    try:
        return path.replace(processing_path)
    except FileNotFoundError:
        return None


def _load_request(path: Path) -> AccountRequest:
    if path.is_symlink():
        raise ValueError('Refusing to process symlinked request')
    with path.open('r', encoding='utf-8') as handle:
        payload = json.load(handle)
    if payload.get('version') != 1:
        raise ValueError('Unsupported request version')
    username = payload.get('username')
    password_hash = payload.get('password_hash')
    requested_at = payload.get('requested_at')
    if not all([username, password_hash, requested_at]):
        raise ValueError('Invalid request payload')
    return AccountRequest(username=username, password_hash=password_hash, requested_at=requested_at)


def _handle_failed_request(path: Path, request: AccountRequest | None, error: Exception) -> None:
    failed_payload = {
        'version': request.version if request else 1,
        'username': request.username if request else None,
        'requested_at': request.requested_at if request else None,
        'error': str(error),
    }
    failed_path = path.with_name(f'{path.name}.failed')
    _write_json_secure(failed_path, failed_payload)
    path.unlink(missing_ok=True)


def _run_coroutine(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: list[object] = []
    error: list[BaseException] = []

    def runner():
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:
            error.append(exc)

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


def _safe_upsert_status(username: str, status: str, error: str | None) -> None:
    try:
        _run_coroutine(upsert_account_provisioning(username, status, error))
    except Exception:
        logging.exception('Failed to update provisioning status for %s', username)


def process_queue_once(queue_dir: str | None = None) -> int:
    queue_path = _queue_dir(queue_dir)
    processed = 0
    for request_path in _iter_requests(queue_path):
        claimed = _claim_request(request_path)
        if claimed is None:
            continue
        request: AccountRequest | None = None
        try:
            request = _load_request(claimed)
            username_error = validate_username(request.username)
            if username_error:
                raise ValueError(username_error)
            if not request.password_hash.startswith('$2'):
                raise ValueError('Invalid password hash format')
            _safe_upsert_status(request.username, PROVISIONING_STATUS_PROCESSING, None)
            if user_exists(request.username):
                logging.info('User %s already exists, dropping request.', request.username)
                _safe_upsert_status(request.username, PROVISIONING_STATUS_COMPLETED, None)
                claimed.unlink(missing_ok=True)
                processed += 1
                continue
            create_student_account(
                request.username,
                request.password_hash,
                teacher_username=TEACHER_USERNAME,
                students_group=STUDENTS_GROUP,
                home_base=STUDENTS_HOME_BASE,
                default_shell=STUDENT_DEFAULT_SHELL,
                use_sudo=False,
                password_is_hashed=True,
            )
            _safe_upsert_status(request.username, PROVISIONING_STATUS_COMPLETED, None)
            claimed.unlink(missing_ok=True)
            processed += 1
        except Exception as exc:
            logging.exception('Failed to provision account from %s', claimed)
            if request:
                _safe_upsert_status(request.username, PROVISIONING_STATUS_FAILED, str(exc))
            try:
                _handle_failed_request(claimed, request, exc)
            except Exception:
                claimed.unlink(missing_ok=True)
            processed += 1
    return processed


def run_worker(
    *,
    queue_dir: str | None = None,
    poll_interval: float = 5.0,
    once: bool = False,
) -> None:
    while True:
        processed = process_queue_once(queue_dir)
        if once:
            return
        if processed == 0:
            time.sleep(poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description='Provision student accounts from queue.')
    parser.add_argument('--queue-dir', default=None, help='Queue directory path')
    parser.add_argument('--poll-interval', type=float, default=5.0, help='Polling interval in seconds')
    parser.add_argument('--once', action='store_true', help='Process queue once and exit')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_worker(queue_dir=args.queue_dir, poll_interval=args.poll_interval, once=args.once)


if __name__ == '__main__':
    main()
