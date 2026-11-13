"""
classes_routes.py
Управление классами, участниками и пригласительными ссылками.
Проект: «Высший балл»
"""

import hashlib
import secrets
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_routes import get_connection, get_current_user


router = APIRouter(
    prefix="/api/classes",
    tags=["Классы"]
)

INVITE_DAYS = 7


# =========================================================
# DATABASE
# =========================================================

def init_classes_tables():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                subject_code TEXT NOT NULL,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(teacher_id)
                    REFERENCES auth_users(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(subject_code)
                    REFERENCES subjects(subject_code)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS class_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                joined_at TEXT NOT NULL,
                left_at TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(class_id)
                    REFERENCES classes(id)
                    ON DELETE CASCADE,
                FOREIGN KEY(student_id)
                    REFERENCES auth_users(id)
                    ON DELETE CASCADE,
                UNIQUE(class_id, student_id),
                CHECK(status IN ('active', 'left', 'removed'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS class_invites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                revoked_at TEXT,
                FOREIGN KEY(class_id)
                    REFERENCES classes(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_classes_teacher
            ON classes(teacher_id, is_active)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_class_members_student
            ON class_members(student_id, status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_class_members_class
            ON class_members(class_id, status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_class_invites_class
            ON class_invites(class_id, expires_at)
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_unrevoked_invite_per_class
            ON class_invites(class_id)
            WHERE revoked_at IS NULL
        """)

        member_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(class_members)"
            ).fetchall()
        }

        if "status" not in member_columns:
            conn.execute("""
                ALTER TABLE class_members
                ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
            """)

        if "joined_at" not in member_columns:
            conn.execute("""
                ALTER TABLE class_members
                ADD COLUMN joined_at TEXT
            """)

        if "left_at" not in member_columns:
            conn.execute("""
                ALTER TABLE class_members
                ADD COLUMN left_at TEXT
            """)

        if "updated_at" not in member_columns:
            conn.execute("""
                ALTER TABLE class_members
                ADD COLUMN updated_at TEXT
            """)

        conn.execute("""
            UPDATE class_members
            SET joined_at = COALESCE(joined_at, CURRENT_TIMESTAMP),
                updated_at = COALESCE(updated_at, CURRENT_TIMESTAMP)
        """)


# =========================================================
# MODELS
# =========================================================

class ClassCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    subject_code: str = Field(min_length=2, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)


class ClassUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    subject_code: Optional[str] = Field(default=None, min_length=2, max_length=50)
    description: Optional[str] = Field(default=None, max_length=2000)


class JoinClassRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)


# =========================================================
# HELPERS
# =========================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_teacher(user: dict):
    if user["role"] != "teacher":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только учителям."
        )
    return user


def require_student(user: dict):
    if user["role"] != "student":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только ученикам."
        )
    return user


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def table_exists(conn, table_name: str) -> bool:
    return conn.execute("""
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
    """, (table_name,)).fetchone() is not None


def get_class_or_404(conn, class_id: int):
    row = conn.execute("""
        SELECT
            c.id,
            c.teacher_id,
            c.name,
            c.subject_code,
            c.description,
            c.is_active,
            c.created_at,
            c.updated_at,
            s.name AS subject_name
        FROM classes c
        JOIN subjects s
            ON s.subject_code = c.subject_code
        WHERE c.id = ?
    """, (class_id,)).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Класс не найден.")

    return row


def ensure_teacher_class(conn, class_id: int, teacher_id: int):
    class_data = get_class_or_404(conn, class_id)

    if class_data["teacher_id"] != teacher_id:
        raise HTTPException(
            status_code=403,
            detail="У вас нет доступа к этому классу."
        )

    if not class_data["is_active"]:
        raise HTTPException(
            status_code=409,
            detail="Класс деактивирован."
        )

    return class_data


def ensure_student_membership(conn, class_id: int, student_id: int):
    row = conn.execute("""
        SELECT id
        FROM class_members
        WHERE class_id = ?
          AND student_id = ?
          AND status = 'active'
    """, (class_id, student_id)).fetchone()

    if row is None:
        raise HTTPException(
            status_code=403,
            detail="Вы не состоите в этом классе."
        )


def serialize_class(row, members_count=None):
    result = {
        "id": row["id"],
        "teacher_id": row["teacher_id"],
        "name": row["name"],
        "subject_code": row["subject_code"],
        "subject_name": row["subject_name"],
        "description": row["description"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"]
    }

    if members_count is not None:
        result["members_count"] = members_count

    return result


# =========================================================
# CREATE CLASS
# =========================================================

@router.post("", status_code=201)
def create_class(
    data: ClassCreate,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    name = data.name.strip()
    subject_code = data.subject_code.strip().lower()
    description = data.description.strip() if data.description else None

    if not name:
        raise HTTPException(status_code=422, detail="Название класса не может быть пустым.")

    now = now_iso()

    with get_connection() as conn:
        subject = conn.execute("""
            SELECT subject_code
            FROM subjects
            WHERE subject_code = ?
              AND is_active = 1
        """, (subject_code,)).fetchone()

        if subject is None:
            raise HTTPException(
                status_code=422,
                detail="Выбранный предмет не найден или отключён."
            )

        cursor = conn.execute("""
            INSERT INTO classes (
                teacher_id, name, subject_code, description,
                is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, 1, ?, ?)
        """, (
            current_user["id"],
            name,
            subject_code,
            description,
            now,
            now
        ))

        class_id = cursor.lastrowid
        row = get_class_or_404(conn, class_id)

    return {
        "message": "Класс создан.",
        "class": serialize_class(row, 0)
    }


# =========================================================
# LIST CLASSES
# =========================================================

@router.get("")
def get_classes(current_user=Depends(get_current_user)):
    with get_connection() as conn:
        if current_user["role"] == "teacher":
            rows = conn.execute("""
                SELECT
                    c.id, c.teacher_id, c.name, c.subject_code,
                    c.description, c.is_active, c.created_at,
                    c.updated_at, s.name AS subject_name,
                    COUNT(cm.id) AS members_count
                FROM classes c
                JOIN subjects s ON s.subject_code = c.subject_code
                LEFT JOIN class_members cm
                    ON cm.class_id = c.id
                   AND cm.status = 'active'
                WHERE c.teacher_id = ?
                GROUP BY c.id
                ORDER BY c.created_at DESC
            """, (current_user["id"],)).fetchall()

        elif current_user["role"] == "student":
            rows = conn.execute("""
                SELECT
                    c.id, c.teacher_id, c.name, c.subject_code,
                    c.description, c.is_active, c.created_at,
                    c.updated_at, s.name AS subject_name,
                    u.username AS teacher_username,
                    cm.joined_at
                FROM class_members cm
                JOIN classes c ON c.id = cm.class_id
                JOIN subjects s ON s.subject_code = c.subject_code
                JOIN auth_users u ON u.id = c.teacher_id
                WHERE cm.student_id = ?
                  AND cm.status = 'active'
                  AND c.is_active = 1
                ORDER BY cm.joined_at DESC
            """, (current_user["id"],)).fetchall()

            return {
                "classes": [
                    {
                        **serialize_class(row),
                        "teacher_username": row["teacher_username"],
                        "joined_at": row["joined_at"]
                    }
                    for row in rows
                ],
                "total": len(rows)
            }

        else:
            rows = conn.execute("""
                SELECT
                    c.id, c.teacher_id, c.name, c.subject_code,
                    c.description, c.is_active, c.created_at,
                    c.updated_at, s.name AS subject_name,
                    COUNT(cm.id) AS members_count
                FROM classes c
                JOIN subjects s ON s.subject_code = c.subject_code
                LEFT JOIN class_members cm
                    ON cm.class_id = c.id
                   AND cm.status = 'active'
                GROUP BY c.id
                ORDER BY c.created_at DESC
            """).fetchall()

    return {
        "classes": [
            serialize_class(row, row["members_count"])
            for row in rows
        ],
        "total": len(rows)
    }


# =========================================================
# CLASS DETAILS AND MEMBERS
# =========================================================

@router.get("/{class_id}")
def get_class(
    class_id: int,
    current_user=Depends(get_current_user)
):
    with get_connection() as conn:
        class_data = get_class_or_404(conn, class_id)

        if current_user["role"] == "teacher":
            if class_data["teacher_id"] != current_user["id"]:
                raise HTTPException(status_code=403, detail="Нет доступа к классу.")
            members = conn.execute("""
                SELECT
                    u.id AS student_id,
                    u.username,
                    u.email,
                    cm.status,
                    cm.joined_at,
                    cm.updated_at
                FROM class_members cm
                JOIN auth_users u ON u.id = cm.student_id
                WHERE cm.class_id = ?
                  AND cm.status = 'active'
                ORDER BY u.username COLLATE NOCASE
            """, (class_id,)).fetchall()

            return {
                "class": serialize_class(class_data, len(members)),
                "members": [dict(row) for row in members]
            }

        if current_user["role"] == "student":
            ensure_student_membership(conn, class_id, current_user["id"])
            teacher = conn.execute("""
                SELECT username
                FROM auth_users
                WHERE id = ?
            """, (class_data["teacher_id"],)).fetchone()

            return {
                "class": serialize_class(class_data),
                "teacher_username": teacher["username"] if teacher else None
            }

        raise HTTPException(status_code=403, detail="Недостаточно прав.")


# =========================================================
# UPDATE CLASS
# =========================================================

@router.patch("/{class_id}")
def update_class(
    class_id: int,
    data: ClassUpdate,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Не переданы поля для изменения.")

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        class_data = ensure_teacher_class(conn, class_id, current_user["id"])

        if "subject_code" in changes:
            subject_code = (changes["subject_code"] or "").strip().lower()
            subject = conn.execute("""
                SELECT subject_code
                FROM subjects
                WHERE subject_code = ? AND is_active = 1
            """, (subject_code,)).fetchone()

            if subject is None:
                raise HTTPException(status_code=422, detail="Предмет не найден или отключён.")

            if subject_code != class_data["subject_code"]:
                has_variants = table_exists(conn, "variants") and conn.execute(
                    "SELECT 1 FROM variants WHERE class_id = ? LIMIT 1",
                    (class_id,)
                ).fetchone()
                if has_variants:
                    raise HTTPException(
                        status_code=409,
                        detail="Нельзя менять предмет класса после создания вариантов."
                    )
            changes["subject_code"] = subject_code

        if "name" in changes:
            changes["name"] = (changes["name"] or "").strip()
            if not changes["name"]:
                raise HTTPException(status_code=422, detail="Название класса не может быть пустым.")

        if "description" in changes:
            changes["description"] = (
                changes["description"].strip()
                if changes["description"] else None
            )

        changes["updated_at"] = now_iso()
        columns = ", ".join(f"{key} = ?" for key in changes)
        conn.execute(
            f"UPDATE classes SET {columns} WHERE id = ?",
            (*changes.values(), class_id)
        )
        updated = get_class_or_404(conn, class_id)

    return {
        "message": "Данные класса обновлены.",
        "class": serialize_class(updated)
    }


# =========================================================
# DEACTIVATE CLASS
# =========================================================

@router.delete("/{class_id}")
def deactivate_class(
    class_id: int,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_teacher_class(conn, class_id, current_user["id"])
        now = now_iso()

        conn.execute("""
            UPDATE classes
            SET is_active = 0, updated_at = ?
            WHERE id = ?
        """, (now, class_id))

        conn.execute("""
            UPDATE class_invites
            SET revoked_at = ?
            WHERE class_id = ?
              AND revoked_at IS NULL
        """, (now, class_id))

        # Закрываем назначения класса для новых попыток.
        # Уже начатые попытки сохраняются и могут быть завершены.
        if table_exists(conn, "class_assignments"):
            conn.execute("""
                UPDATE class_assignments
                SET status = 'closed'
                WHERE class_id = ?
                  AND status = 'active'
            """, (class_id,))

    return {
        "message": "Класс деактивирован.",
        "class_id": class_id,
        "is_active": False
    }


# =========================================================
# INVITES
# =========================================================

@router.post("/{class_id}/invite", status_code=201)
def create_class_invite(
    class_id: int,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    expires_at = (now + timedelta(days=INVITE_DAYS)).isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_teacher_class(conn, class_id, current_user["id"])

        # Новая ссылка автоматически отзывает предыдущую.
        conn.execute("""
            UPDATE class_invites
            SET revoked_at = ?
            WHERE class_id = ?
              AND revoked_at IS NULL
        """, (created_at, class_id))

        conn.execute("""
            INSERT INTO class_invites (
                class_id, token_hash, created_at, expires_at, revoked_at
            )
            VALUES (?, ?, ?, ?, NULL)
        """, (
            class_id,
            token_digest(token),
            created_at,
            expires_at
        ))

    return {
        "message": "Пригласительная ссылка создана.",
        "class_id": class_id,
        "invite_url": f"/join/{token}",
        "expires_at": expires_at,
        "valid_days": INVITE_DAYS
    }


@router.get("/{class_id}/invite")
def get_class_invite_status(
    class_id: int,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        ensure_teacher_class(conn, class_id, current_user["id"])
        invite = conn.execute("""
            SELECT created_at, expires_at, revoked_at
            FROM class_invites
            WHERE class_id = ?
              AND revoked_at IS NULL
            ORDER BY id DESC
            LIMIT 1
        """, (class_id,)).fetchone()

    if invite is None:
        return {"class_id": class_id, "active_invite": None}

    expires = datetime.fromisoformat(invite["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    active = expires > datetime.now(timezone.utc)

    return {
        "class_id": class_id,
        "active_invite": {
            "created_at": invite["created_at"],
            "expires_at": invite["expires_at"],
            "is_valid": active
        }
    }


@router.delete("/{class_id}/invite")
def revoke_class_invite(
    class_id: int,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_teacher_class(conn, class_id, current_user["id"])
        cursor = conn.execute("""
            UPDATE class_invites
            SET revoked_at = ?
            WHERE class_id = ?
              AND revoked_at IS NULL
        """, (now_iso(), class_id))

    return {
        "message": "Пригласительная ссылка отозвана.",
        "class_id": class_id,
        "revoked": cursor.rowcount > 0
    }


@router.post("/join")
def join_class(
    data: JoinClassRequest,
    current_user=Depends(get_current_user)
):
    require_student(current_user)

    token = data.token.strip()
    now = datetime.now(timezone.utc)
    now_text = now.isoformat()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        invite = conn.execute("""
            SELECT
                i.id AS invite_id,
                i.class_id,
                i.expires_at,
                i.revoked_at,
                c.is_active
            FROM class_invites i
            JOIN classes c ON c.id = i.class_id
            WHERE i.token_hash = ?
        """, (token_digest(token),)).fetchone()

        if invite is None or invite["revoked_at"] is not None:
            raise HTTPException(status_code=404, detail="Пригласительная ссылка недействительна.")

        expires = datetime.fromisoformat(invite["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if expires <= now:
            raise HTTPException(status_code=410, detail="Срок действия приглашения истёк.")

        if not invite["is_active"]:
            raise HTTPException(status_code=409, detail="Класс деактивирован.")

        membership = conn.execute("""
            SELECT id, status
            FROM class_members
            WHERE class_id = ? AND student_id = ?
        """, (invite["class_id"], current_user["id"])).fetchone()

        if membership and membership["status"] == "active":
            raise HTTPException(status_code=409, detail="Вы уже состоите в этом классе.")

        if membership:
            conn.execute("""
                UPDATE class_members
                SET status = 'active',
                    joined_at = ?,
                    left_at = NULL,
                    updated_at = ?
                WHERE id = ?
            """, (now_text, now_text, membership["id"]))
        else:
            conn.execute("""
                INSERT INTO class_members (
                    class_id, student_id, status, joined_at, left_at, updated_at
                )
                VALUES (?, ?, 'active', ?, NULL, ?)
            """, (
                invite["class_id"],
                current_user["id"],
                now_text,
                now_text
            ))

        class_data = get_class_or_404(conn, invite["class_id"])

    return {
        "message": "Вы присоединились к классу.",
        "class": serialize_class(class_data)
    }


# =========================================================
# LEAVE / REMOVE MEMBERS
# =========================================================

@router.delete("/{class_id}/leave")
def leave_class(
    class_id: int,
    current_user=Depends(get_current_user)
):
    require_student(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        membership = conn.execute("""
            SELECT id
            FROM class_members
            WHERE class_id = ?
              AND student_id = ?
              AND status = 'active'
        """, (class_id, current_user["id"])).fetchone()

        if membership is None:
            raise HTTPException(status_code=404, detail="Вы не состоите в этом классе.")

        now = now_iso()
        conn.execute("""
            UPDATE class_members
            SET status = 'left', left_at = ?, updated_at = ?
            WHERE id = ?
        """, (now, now, membership["id"]))

    return {
        "message": "Вы покинули класс.",
        "class_id": class_id
    }


@router.delete("/{class_id}/members/{student_id}")
def remove_class_member(
    class_id: int,
    student_id: int,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_teacher_class(conn, class_id, current_user["id"])

        membership = conn.execute("""
            SELECT id
            FROM class_members
            WHERE class_id = ?
              AND student_id = ?
              AND status = 'active'
        """, (class_id, student_id)).fetchone()

        if membership is None:
            raise HTTPException(status_code=404, detail="Активный участник класса не найден.")

        now = now_iso()
        conn.execute("""
            UPDATE class_members
            SET status = 'removed', left_at = ?, updated_at = ?
            WHERE id = ?
        """, (now, now, membership["id"]))

    return {
        "message": "Ученик исключён из класса.",
        "class_id": class_id,
        "student_id": student_id
    }


# =========================================================
# INITIALIZATION
# =========================================================

init_classes_tables()
