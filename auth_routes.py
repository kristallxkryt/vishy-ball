
"""
auth_routes.py
Регистрация и авторизация пользователей проекта «Высший балл».
"""

import hashlib
import hmac
import os
import secrets
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field


DB_PATH = Path(__file__).resolve().parent / "users.db"

router = APIRouter(
    prefix="/api/auth",
    tags=["Авторизация"]
)

ITERATIONS = 310_000
SESSION_DAYS = 7

security = HTTPBearer(auto_error=False)


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_auth_tables():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'student'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY(user_id)
                    REFERENCES auth_users(id)
                    ON DELETE CASCADE
            )
        """)

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(auth_users)"
            ).fetchall()
        }

        if "role" not in columns:
            conn.execute("""
                ALTER TABLE auth_users
                ADD COLUMN role TEXT NOT NULL DEFAULT 'student'
            """)

        if "is_active" not in columns:
            conn.execute("""
                ALTER TABLE auth_users
                ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
            """)

        conn.execute("""
            UPDATE auth_users
            SET role = 'student'
            WHERE role IS NULL OR role = ''
        """)

        conn.execute("""
            UPDATE auth_users
            SET is_active = 1
            WHERE is_active IS NULL
        """)


# =========================================================
# PASSWORD HASHING
# =========================================================

def hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        ITERATIONS
    )

    return digest.hex()


# =========================================================
# REQUEST MODELS
# =========================================================

class RegisterRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=32,
        pattern=r"^[A-Za-zА-Яа-яЁё0-9_]+$"
    )

    email: EmailStr | None = None

    password: str = Field(
        min_length=8,
        max_length=128
    )

    role: Literal["student", "teacher"] = "student"


class LoginRequest(BaseModel):
    login: str = Field(
        min_length=3,
        max_length=254
    )

    password: str = Field(
        min_length=8,
        max_length=128
    )


# =========================================================
# SESSION MANAGEMENT
# =========================================================

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    expires = (
        datetime.now(timezone.utc)
        + timedelta(days=SESSION_DAYS)
    )

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions
            (token_hash, user_id, expires_at)
            VALUES (?, ?, ?)
            """,
            (
                token_hash,
                user_id,
                expires.isoformat()
            )
        )

    return token


# =========================================================
# REGISTRATION
# =========================================================

@router.post("/register", status_code=201)
def register(data: RegisterRequest):
    username = data.username.strip()
    email = (str(data.email).strip().lower() if data.email else f"{username.lower()}.{secrets.token_hex(8)}@accounts.invalid")
    role = data.role

    salt = os.urandom(16)

    password_hash = hash_password(
        data.password,
        salt
    )

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO auth_users (
                    username,
                    email,
                    password_hash,
                    salt,
                    created_at,
                    role,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    username,
                    email,
                    password_hash,
                    salt.hex(),
                    datetime.now(timezone.utc).isoformat(),
                    role
                )
            )

            user_id = cursor.lastrowid

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Такой логин или email уже зарегистрирован."
        )

    return {
        "message": "Аккаунт успешно создан!",
        "user": {
            "id": user_id,
            "username": username,
            "email": None if email.endswith("@accounts.invalid") else email,
            "role": role
        }
    }


# =========================================================
# LOGIN
# =========================================================

@router.post("/login")
def login(data: LoginRequest):
    value = data.login.strip()

    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT
                id,
                username,
                email,
                password_hash,
                salt,
                role,
                is_active
            FROM auth_users
            WHERE username = ? COLLATE NOCASE
               OR email = ? COLLATE NOCASE
            """,
            (value, value)
        ).fetchone()

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Неверный логин или пароль."
        )

    salt = bytes.fromhex(user["salt"])

    candidate = hash_password(
        data.password,
        salt
    )

    if not hmac.compare_digest(
        candidate,
        user["password_hash"]
    ):
        raise HTTPException(
            status_code=401,
            detail="Неверный логин или пароль."
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="Ваш аккаунт заблокирован."
        )

    token = create_session(user["id"])

    return {
        "message": "Вход выполнен!",
        "access_token": token,
        "token_type": "bearer",
        "expires_in_days": SESSION_DAYS,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "email": None if user["email"].endswith("@accounts.invalid") else user["email"],
            "role": user["role"]
        }
    }


# =========================================================
# CURRENT USER
# =========================================================

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Необходимо авторизоваться."
        )

    token = credentials.credentials.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Пустой токен."
        )

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    now = datetime.now(timezone.utc)
    expired = False

    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                u.email,
                u.role,
                u.is_active,
                s.expires_at
            FROM auth_sessions s
            JOIN auth_users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,)
        ).fetchone()

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Сессия не найдена."
            )

        expires_at = datetime.fromisoformat(
            user["expires_at"]
        )

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(
                tzinfo=timezone.utc
            )

        if expires_at <= now:
            conn.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (token_hash,)
            )
            expired = True

    if expired:
        raise HTTPException(
            status_code=401,
            detail="Срок действия сессии истёк."
        )

    if not user["is_active"]:
        raise HTTPException(
            status_code=403,
            detail="Ваш аккаунт заблокирован."
        )

    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "role": user["role"]
    }


# =========================================================
# ROLE CHECKS
# =========================================================

def require_admin(
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только администраторам."
        )

    return current_user


def require_teacher(
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "teacher":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только учителям."
        )

    return current_user


def require_student(
    current_user: dict = Depends(get_current_user)
):
    if current_user["role"] != "student":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только ученикам."
        )

    return current_user


# =========================================================
# ME
# =========================================================

@router.get("/me")
def get_me(
    current_user: dict = Depends(get_current_user)
):
    return current_user


# =========================================================
# LOGOUT
# =========================================================

@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
):
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Необходимо авторизоваться."
        )

    token = credentials.credentials.strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Пустой токен."
        )

    token_hash = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    with get_connection() as conn:
        conn.execute(
            """
            DELETE FROM auth_sessions
            WHERE token_hash = ?
            """,
            (token_hash,)
        )

    return {
        "message": "Вы успешно вышли из аккаунта."
    }


# =========================================================
# INITIALIZATION
# =========================================================

init_auth_tables()
