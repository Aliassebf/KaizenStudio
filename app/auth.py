from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .db import get_connection


SESSION_COOKIE = "kaizen_session"
SESSION_HOURS = 12
PASSWORD_ITERATIONS = 310_000
_DUMMY_PASSWORD_HASH = (
    f"pbkdf2_sha256${PASSWORD_ITERATIONS}$"
    f"{'00' * 16}$"
    f"{hashlib.pbkdf2_hmac('sha256', b'not-a-real-password', bytes(16), PASSWORD_ITERATIONS).hex()}"
)
_attempt_lock = threading.Lock()
_failed_logins: dict[str, deque[float]] = defaultdict(deque)
_ATTEMPT_WINDOW_SECONDS = 15 * 60


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def login_is_rate_limited(username: str, remote_ip: str) -> bool:
    now = time.monotonic()
    keys = (f"user:{username.casefold()}", f"ip:{remote_ip}")
    limits = (10, 30)
    with _attempt_lock:
        for key, attempts in tuple(_failed_logins.items()):
            while attempts and now - attempts[0] > _ATTEMPT_WINDOW_SECONDS:
                attempts.popleft()
            if not attempts:
                _failed_logins.pop(key, None)
        for key, limit in zip(keys, limits):
            attempts = _failed_logins.get(key, ())
            if len(attempts) >= limit:
                return True
    return False


def record_failed_login(username: str, remote_ip: str) -> None:
    now = time.monotonic()
    with _attempt_lock:
        _failed_logins[f"user:{username.casefold()}"].append(now)
        _failed_logins[f"ip:{remote_ip}"].append(now)


def clear_failed_logins(username: str, remote_ip: str) -> None:
    with _attempt_lock:
        _failed_logins.pop(f"user:{username.casefold()}", None)
        _failed_logins.pop(f"ip:{remote_ip}", None)


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, user_id, expires_at),
        )
    return token


def get_session_user(token: str | None) -> dict[str, int | str] | None:
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.is_admin
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
              AND u.is_active = 1
            """,
            (token_hash, datetime.now(timezone.utc).isoformat()),
        ).fetchone()
    return dict(row) if row else None


def revoke_session(token: str | None) -> None:
    if not token:
        return
    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    with get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (token_hash,))


def user_count() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
    return int(row["count"])
