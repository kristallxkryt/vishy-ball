
"""
users_routes.py
Управление аккаунтами пользователей проекта «Высший балл».
Доступно только администраторам.
"""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth_routes import get_connection, require_admin


router = APIRouter(
    prefix="/api/users",
    tags=["Управление пользователями"]
)


# =========================================================
# REQUEST MODELS
# =========================================================

class RoleUpdate(BaseModel):
    role: Literal["student", "teacher", "admin"]


class StatusUpdate(BaseModel):
    is_active: bool


# =========================================================
# HELPERS
# =========================================================

def get_user_or_404(conn, user_id: int):
    user = conn.execute(
        """
        SELECT
            id,
            username,
            email,
            created_at,
            role,
            is_active
        FROM auth_users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Пользователь не найден."
        )

    return user


def serialize_user(user):
    return {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "created_at": user["created_at"],
        "role": user["role"],
        "is_active": bool(user["is_active"])
    }


def count_active_admins(conn) -> int:
    result = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM auth_users
        WHERE role = 'admin'
          AND is_active = 1
        """
    ).fetchone()

    return result["total"]


def ensure_not_self(
    current_user: dict,
    target_user_id: int,
    action: str
):
    if current_user["id"] == target_user_id:
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя выполнить это действие со своим аккаунтом: {action}."
        )


# =========================================================
# GET USERS
# =========================================================

@router.get("")
def get_users(
    q: str | None = Query(
        default=None,
        max_length=100,
        description="Поиск по логину или email"
    ),
    role: Literal["student", "teacher", "admin"] | None = None,
    status: Literal["active", "blocked"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(require_admin)
):
    conditions = []
    params = []

    if q and q.strip():
        search = f"%{q.strip()}%"

        conditions.append(
            "(username LIKE ? OR email LIKE ?)"
        )

        params.extend([search, search])

    if role:
        conditions.append("role = ?")
        params.append(role)

    if status == "active":
        conditions.append("is_active = 1")

    elif status == "blocked":
        conditions.append("is_active = 0")

    where_sql = (
        "WHERE " + " AND ".join(conditions)
        if conditions else ""
    )

    with get_connection() as conn:
        total = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM auth_users
            {where_sql}
            """,
            params
        ).fetchone()["total"]

        rows = conn.execute(
            f"""
            SELECT
                id,
                username,
                email,
                created_at,
                role,
                is_active
            FROM auth_users
            {where_sql}
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        ).fetchall()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "users": [
            serialize_user(user)
            for user in rows
        ]
    }


# =========================================================
# GET USER DETAILS
# =========================================================

@router.get("/{user_id}")
def get_user(
    user_id: int,
    current_user: dict = Depends(require_admin)
):
    with get_connection() as conn:
        user = get_user_or_404(conn, user_id)

        now = datetime.now(timezone.utc).isoformat()

        sessions = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM auth_sessions
            WHERE user_id = ?
              AND expires_at > ?
            """,
            (user_id, now)
        ).fetchone()["total"]

    result = serialize_user(user)
    result["active_sessions"] = sessions

    return {
        "user": result
    }


# =========================================================
# UPDATE ROLE
# =========================================================

@router.patch("/{user_id}/role")
def update_user_role(
    user_id: int,
    data: RoleUpdate,
    current_user: dict = Depends(require_admin)
):
    ensure_not_self(
        current_user,
        user_id,
        "изменение роли"
    )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        user = get_user_or_404(conn, user_id)

        old_role = user["role"]
        new_role = data.role

        if old_role == new_role:
            return {
                "message": "Роль пользователя не изменилась.",
                "user": serialize_user(user)
            }

        if (
            old_role == "admin"
            and new_role != "admin"
            and user["is_active"]
        ):
            if count_active_admins(conn) <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя понизить роль последнего активного администратора."
                )

        conn.execute(
            """
            UPDATE auth_users
            SET role = ?
            WHERE id = ?
            """,
            (new_role, user_id)
        )

        # Завершаем все действующие сессии,
        # чтобы пользователь повторно авторизовался
        # уже с новой ролью.

        cursor = conn.execute(
            """
            DELETE FROM auth_sessions
            WHERE user_id = ?
            """,
            (user_id,)
        )

        revoked_sessions = cursor.rowcount

        updated_user = get_user_or_404(conn, user_id)

    return {
        "message": "Роль пользователя успешно изменена. Все его сессии завершены.",
        "revoked_sessions": revoked_sessions,
        "user": serialize_user(updated_user)
    }


# =========================================================
# UPDATE STATUS
# =========================================================

@router.patch("/{user_id}/status")
def update_user_status(
    user_id: int,
    data: StatusUpdate,
    current_user: dict = Depends(require_admin)
):
    ensure_not_self(
        current_user,
        user_id,
        "изменение статуса"
    )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        user = get_user_or_404(conn, user_id)

        old_status = bool(user["is_active"])
        new_status = data.is_active

        if old_status == new_status:
            return {
                "message": "Статус пользователя не изменился.",
                "user": serialize_user(user)
            }

        if (
            not new_status
            and user["role"] == "admin"
            and old_status
        ):
            if count_active_admins(conn) <= 1:
                raise HTTPException(
                    status_code=400,
                    detail="Нельзя заблокировать последнего активного администратора."
                )

        conn.execute(
            """
            UPDATE auth_users
            SET is_active = ?
            WHERE id = ?
            """,
            (int(new_status), user_id)
        )

        if not new_status:
            conn.execute(
                """
                DELETE FROM auth_sessions
                WHERE user_id = ?
                """,
                (user_id,)
            )

        updated_user = get_user_or_404(conn, user_id)

    return {
        "message": (
            "Пользователь разблокирован."
            if new_status
            else "Пользователь заблокирован. Все его сессии завершены."
        ),
        "user": serialize_user(updated_user)
    }


# =========================================================
# REVOKE USER SESSIONS
# =========================================================

@router.delete("/{user_id}/sessions")
def revoke_user_sessions(
    user_id: int,
    current_user: dict = Depends(require_admin)
):
    ensure_not_self(
        current_user,
        user_id,
        "завершение собственных сессий"
    )

    with get_connection() as conn:
        get_user_or_404(conn, user_id)

        cursor = conn.execute(
            """
            DELETE FROM auth_sessions
            WHERE user_id = ?
            """,
            (user_id,)
        )

        deleted_count = cursor.rowcount

    return {
        "message": "Сессии пользователя завершены.",
        "user_id": user_id,
        "revoked_sessions": deleted_count
    }
