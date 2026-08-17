import hashlib
import hmac
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "users.db"
PBKDF2_ITERATIONS = 260_000
MIN_PASSWORD_LENGTH = 8
USERNAME_PATTERN = re.compile(r"^[a-z0-9_]{3,32}$")


@contextmanager
def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return digest.hex(), salt.hex()


def sign_up(username: str, password: str, confirm_password: str) -> tuple[bool, str]:
    """Create a new account. Returns (success, message)."""
    username = username.strip().lower()

    if not USERNAME_PATTERN.match(username):
        return False, "Username must be 3-32 characters: lowercase letters, numbers, underscore only."
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password != confirm_password:
        return False, "Passwords don't match."

    password_hash, salt = _hash_password(password)
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
                (username, password_hash, salt),
            )
    except sqlite3.IntegrityError:
        return False, "That username is already taken."
    return True, "Account created. You can sign in now."


def sign_in(username: str, password: str) -> tuple[bool, str]:
    """Verify credentials. Returns (success, message). Never reveals whether
    the failure was a bad username or a bad password."""
    username = username.strip().lower()

    with _connect() as conn:
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?", (username,)
        ).fetchone()

    if row is None:
        return False, "Invalid username or password."

    stored_hash, salt_hex = row
    candidate_hash, _ = _hash_password(password, bytes.fromhex(salt_hex))
    if not hmac.compare_digest(candidate_hash, stored_hash):
        return False, "Invalid username or password."
    return True, "Signed in."
