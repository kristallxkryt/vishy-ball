"""
Высший балл — часть 2: база данных и работа с аккаунтами.

Файл: database.py
Использует SQLite из стандартной библиотеки Python — отдельно устанавливать
базу данных или дополнительные пакеты не нужно.

Возможности:
- автоматическое создание файла users.db и таблицы users;
- регистрация пользователя;
- проверка логина и пароля;
- безопасное хранение паролей в виде PBKDF2-хеша (не в открытом виде).

Пример использования:
    from database import init_db, register_user, authenticate_user

    init_db()
    user_id = register_user("student", "student@example.com", "StrongPass123")
    user = authenticate_user("student", "StrongPass123")
"""

import hashlib
import hmac
import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().with_name("users.db")
_HASH_NAME = "sha256"
_ITERATIONS = 310_000


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    """Создаёт таблицу пользователей, если её ещё нет."""
    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def _hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        _HASH_NAME,
        password.encode("utf-8"),
        salt,
        _ITERATIONS,
    )
    # Соль и хеш сохраняются вместе; исходный пароль не сохраняется.
    return f"pbkdf2_{_HASH_NAME}${_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_text, salt_hex, expected_hex = stored_hash.split("$")
        if algorithm != f"pbkdf2_{_HASH_NAME}":
            return False
        actual = hashlib.pbkdf2_hmac(
            _HASH_NAME,
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations_text),
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def register_user(username: str, email: str, password: str) -> int:
    """
    Регистрирует пользователя и возвращает его ID.

    Поднимает ValueError при некорректных данных или занятом логине/email.
    """
    username = username.strip()
    email = email.strip().lower()

    if len(username) < 3 or len(username) > 32:
        raise ValueError("Логин должен содержать от 3 до 32 символов.")
    if "@" not in email or len(email) > 254:
        raise ValueError("Укажите корректный адрес электронной почты.")
    if len(password) < 8:
        raise ValueError("Пароль должен содержать не менее 8 символов.")

    password_hash = _hash_password(password)

    try:
        with _connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (username, email, password_hash)
                VALUES (?, ?, ?)
                """,
                (username, email, password_hash),
            )
            return int(cursor.lastrowid)
    except sqlite3.IntegrityError as error:
        raise ValueError("Такой логин или адрес электронной почты уже занят.") from error


def authenticate_user(username: str, password: str) -> Optional[dict]:
    """
    Проверяет логин и пароль.
    Возвращает безопасные данные пользователя или None.
    """
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, username, email, password_hash, created_at
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (username.strip(),),
        ).fetchone()

    if row is None or not _verify_password(password, row["password_hash"]):
        return None

    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


if __name__ == "__main__":
    init_db()
    print(f"База данных готова: {DB_PATH}")
    print("Таблица пользователей создана или уже существует.")
