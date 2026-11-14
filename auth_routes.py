
"""
auth_routes.py
Регистрация и авторизация пользователей проекта «Высший балл».
"""

import hashlib
import hmac
import os
import secrets
import sqlite3
import json
import smtplib
from email.message import EmailMessage

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


        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_registrations (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                username TEXT NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL,
                code_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS account_email_codes (
                user_id INTEGER NOT NULL,
                purpose TEXT NOT NULL,
                target_email TEXT,
                code_hash TEXT NOT NULL,
                payload_json TEXT,
                expires_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, purpose),
                FOREIGN KEY(user_id) REFERENCES auth_users(id) ON DELETE CASCADE
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

        if "email_verified" not in columns:
            conn.execute("""
                ALTER TABLE auth_users
                ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1
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

    email: EmailStr

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


class VerifyRegistrationRequest(BaseModel):
    email: EmailStr
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


class ResendRegistrationRequest(BaseModel):
    email: EmailStr


class EmailChangeRequest(BaseModel):
    new_email: EmailStr


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ConfirmCodeRequest(BaseModel):
    code: str = Field(min_length=6, max_length=6, pattern=r"^[0-9]{6}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _code_hash(code: str) -> str:
    # Slow derivation makes a database leak much harder to brute-force offline.
    return hashlib.pbkdf2_hmac(
        "sha256",
        code.encode("utf-8"),
        b"vishy-ball-email-verification-v1",
        ITERATIONS
    ).hex()


def _new_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _expires_at() -> str:
    return (_now() + timedelta(minutes=10)).isoformat()


def _send_email_code(recipient: str, subject: str, purpose_text: str, code: str):
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", "").strip() or username
    if not host or not sender:
        raise HTTPException(status_code=503, detail="Отправка писем не настроена. Добавьте SMTP-настройки в переменные окружения.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"Здравствуйте!\n\\n{purpose_text}\\n\\nВаш код подтверждения: {code}\\n"
        "Код действует 10 минут. Никому не сообщайте его.\\n"
        "Если вы не запрашивали это действие, проигнорируйте письмо."
    )
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(host, port, timeout=15) as server:
            if os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}:
                server.starttls()
            if username:
                server.login(username, password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Не удалось отправить письмо. Проверьте SMTP-настройки.") from exc


def _verify_stored_code(row, code: str):
    if row is None:
        raise HTTPException(status_code=400, detail="Код не найден. Запросите новый.")
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= _now():
        raise HTTPException(status_code=400, detail="Срок действия кода истёк. Запросите новый.")
    if row["attempts"] >= 5:
        raise HTTPException(status_code=429, detail="Слишком много попыток. Запросите новый код.")
    if not hmac.compare_digest(row["code_hash"], _code_hash(code)):
        raise HTTPException(status_code=400, detail="Неверный код подтверждения.")


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

@router.post("/register", status_code=202)
def register(data: RegisterRequest):
    username = data.username.strip()
    email = str(data.email).strip().lower()
    role = data.role

    with get_connection() as conn:
        conn.execute(
            "DELETE FROM pending_registrations WHERE expires_at <= ?",
            (_now().isoformat(),)
        )
        existing = conn.execute(
            """
            SELECT 1 FROM auth_users
            WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
            """,
            (username, email)
        ).fetchone()
        pending = conn.execute(
            """
            SELECT 1 FROM pending_registrations
            WHERE username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE
            """,
            (username, email)
        ).fetchone()
    if existing or pending:
        raise HTTPException(status_code=409, detail="Такой логин или email уже зарегистрирован либо ожидает подтверждения.")

    salt = os.urandom(16)
    password_hash = hash_password(data.password, salt)
    code = _new_code()
    _send_email_code(
        email,
        "Подтверждение регистрации — Высший балл",
        "Для завершения регистрации на платформе «Высший балл» введите этот код:",
        code
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO pending_registrations
            (email, username, password_hash, salt, role, code_hash, expires_at, attempts, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                email, username, password_hash, salt.hex(), role,
                _code_hash(code), _expires_at(), _now().isoformat()
            )
        )
    return {"message": "Код подтверждения отправлен на указанную почту.", "verification_required": True}


@router.post("/register/resend")
def resend_registration_code(data: ResendRegistrationRequest):
    email = str(data.email).strip().lower()
    with get_connection() as conn:
        pending = conn.execute(
            "SELECT created_at FROM pending_registrations WHERE email = ? COLLATE NOCASE",
            (email,)
        ).fetchone()
    if pending is None:
        raise HTTPException(status_code=404, detail="Незавершённая регистрация не найдена. Начните регистрацию заново.")
    created = datetime.fromisoformat(pending["created_at"])
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if (_now() - created).total_seconds() < 60:
        raise HTTPException(status_code=429, detail="Повторный код можно запросить через минуту.")
    code = _new_code()
    _send_email_code(
        email,
        "Новый код регистрации — Высший балл",
        "Введите этот код, чтобы завершить регистрацию:",
        code
    )
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE pending_registrations
            SET code_hash = ?, expires_at = ?, attempts = 0, created_at = ?
            WHERE email = ? COLLATE NOCASE
            """,
            (_code_hash(code), _expires_at(), _now().isoformat(), email)
        )
    return {"message": "Новый код отправлен на почту."}


@router.post("/register/verify", status_code=201)
def verify_registration(data: VerifyRegistrationRequest):
    email = str(data.email).strip().lower()
    with get_connection() as conn:
        pending = conn.execute(
            "SELECT * FROM pending_registrations WHERE email = ? COLLATE NOCASE",
            (email,)
        ).fetchone()
        try:
            _verify_stored_code(pending, data.code)
        except HTTPException as exc:
            if pending is not None and exc.status_code == 400 and "Неверный код" in str(exc.detail):
                conn.execute(
                    "UPDATE pending_registrations SET attempts = attempts + 1 WHERE email = ?",
                    (email,)
                )
                conn.commit()
            raise
        cursor = conn.execute(
            """
            INSERT INTO auth_users (
                username, email, password_hash, salt, created_at,
                role, is_active, email_verified
            )
            VALUES (?, ?, ?, ?, ?, ?, 1, 1)
            """,
            (
                pending["username"], email, pending["password_hash"],
                pending["salt"], _now().isoformat(), pending["role"]
            )
        )
        user_id = cursor.lastrowid
        conn.execute("DELETE FROM pending_registrations WHERE email = ?", (email,))
    return {
        "message": "Почта подтверждена, аккаунт создан.",
        "user": {
            "id": user_id, "username": pending["username"],
            "email": email, "role": pending["role"]
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
                is_active,
                email_verified
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

    if not user["email_verified"]:
        raise HTTPException(
            status_code=403,
            detail="Сначала подтвердите адрес электронной почты."
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
            "email": user["email"],
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
# ACCOUNT EMAIL AND PASSWORD CHANGES
# =========================================================

def _current_password_matches(user_id: int, password: str) -> bool:
    with get_connection() as conn:
        user = conn.execute(
            "SELECT password_hash, salt FROM auth_users WHERE id = ?",
            (user_id,)
        ).fetchone()
    if user is None:
        return False
    candidate = hash_password(password, bytes.fromhex(user["salt"]))
    return hmac.compare_digest(candidate, user["password_hash"])


def _store_account_code(user_id: int, purpose: str, target_email: str | None, payload: dict, code: str):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO account_email_codes
            (user_id, purpose, target_email, code_hash, payload_json, expires_at, attempts, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                user_id, purpose, target_email, _code_hash(code),
                json.dumps(payload, ensure_ascii=False), _expires_at(), _now().isoformat()
            )
        )


@router.post("/email-change/request")
def request_email_change(
    data: EmailChangeRequest,
    current_user: dict = Depends(get_current_user)
):
    new_email = str(data.new_email).strip().lower()
    if new_email == current_user["email"].lower():
        raise HTTPException(status_code=400, detail="Это уже текущий адрес почты.")
    with get_connection() as conn:
        duplicate = conn.execute(
            "SELECT 1 FROM auth_users WHERE email = ? COLLATE NOCASE",
            (new_email,)
        ).fetchone()
    if duplicate:
        raise HTTPException(status_code=409, detail="Этот адрес уже используется другим аккаунтом.")
    code = _new_code()
    _send_email_code(
        new_email,
        "Подтверждение новой почты — Высший балл",
        "Чтобы изменить адрес электронной почты аккаунта, введите этот код:",
        code
    )
    _store_account_code(current_user["id"], "email_change", new_email, {}, code)
    return {"message": "Код отправлен на новый адрес почты."}


@router.post("/email-change/confirm")
def confirm_email_change(
    data: ConfirmCodeRequest,
    current_user: dict = Depends(get_current_user)
):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM account_email_codes WHERE user_id = ? AND purpose = 'email_change'",
            (current_user["id"],)
        ).fetchone()
        try:
            _verify_stored_code(row, data.code)
        except HTTPException as exc:
            if row is not None and exc.status_code == 400 and "Неверный код" in str(exc.detail):
                conn.execute(
                    "UPDATE account_email_codes SET attempts = attempts + 1 WHERE user_id = ? AND purpose = 'email_change'",
                    (current_user["id"],)
                )
                conn.commit()
            raise
        new_email = row["target_email"]
        duplicate = conn.execute(
            "SELECT 1 FROM auth_users WHERE email = ? COLLATE NOCASE AND id != ?",
            (new_email, current_user["id"])
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409, detail="Этот адрес уже используется другим аккаунтом.")
        conn.execute(
            "UPDATE auth_users SET email = ?, email_verified = 1 WHERE id = ?",
            (new_email, current_user["id"])
        )
        conn.execute(
            "DELETE FROM account_email_codes WHERE user_id = ? AND purpose = 'email_change'",
            (current_user["id"],)
        )
    return {"message": "Адрес электронной почты успешно изменён.", "user": {**current_user, "email": new_email}}


@router.post("/password-change/request")
def request_password_change(
    data: PasswordChangeRequest,
    current_user: dict = Depends(get_current_user)
):
    if not _current_password_matches(current_user["id"], data.current_password):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно.")
    if hmac.compare_digest(data.current_password, data.new_password):
        raise HTTPException(status_code=400, detail="Новый пароль должен отличаться от текущего.")
    code = _new_code()
    _send_email_code(
        current_user["email"],
        "Подтверждение смены пароля — Высший балл",
        "Чтобы изменить пароль аккаунта, введите этот код:",
        code
    )
    salt = os.urandom(16)
    payload = {"password_hash": hash_password(data.new_password, salt), "salt": salt.hex()}
    _store_account_code(current_user["id"], "password_change", None, payload, code)
    return {"message": "Код отправлен на текущую почту."}


@router.post("/password-change/confirm")
def confirm_password_change(
    data: ConfirmCodeRequest,
    current_user: dict = Depends(get_current_user)
):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM account_email_codes WHERE user_id = ? AND purpose = 'password_change'",
            (current_user["id"],)
        ).fetchone()
        try:
            _verify_stored_code(row, data.code)
        except HTTPException as exc:
            if row is not None and exc.status_code == 400 and "Неверный код" in str(exc.detail):
                conn.execute(
                    "UPDATE account_email_codes SET attempts = attempts + 1 WHERE user_id = ? AND purpose = 'password_change'",
                    (current_user["id"],)
                )
                conn.commit()
            raise
        payload = json.loads(row["payload_json"] or "{}")
        if not payload.get("password_hash") or not payload.get("salt"):
            raise HTTPException(status_code=400, detail="Запрос смены пароля повреждён. Запросите код повторно.")
        conn.execute(
            "UPDATE auth_users SET password_hash = ?, salt = ? WHERE id = ?",
            (payload["password_hash"], payload["salt"], current_user["id"])
        )
        conn.execute("DELETE FROM auth_sessions WHERE user_id = ?", (current_user["id"],))
        conn.execute(
            "DELETE FROM account_email_codes WHERE user_id = ? AND purpose = 'password_change'",
            (current_user["id"],)
        )
    return {"message": "Пароль изменён. Войдите в аккаунт с новым паролем."}


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
