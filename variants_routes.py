"""
variants_routes.py

Создание вариантов ЕГЭ, назначение классам,
выполнение назначенных работ и сохранение прогресса.

Проект: «Высший балл»
"""

import json
import sqlite3

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)

from pydantic import BaseModel, Field

from auth_routes import get_connection, get_current_user
from checking_routes import grade_assignment_attempt


router = APIRouter(
    prefix="/api",
    tags=["Варианты и назначенные работы"]
)


# =========================================================
# DATABASE
# =========================================================

def init_variants_tables():
    with get_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                FOREIGN KEY(teacher_id)
                    REFERENCES auth_users(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(class_id)
                    REFERENCES classes(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS variant_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                variant_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                position INTEGER NOT NULL,

                FOREIGN KEY(variant_id)
                    REFERENCES variants(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(task_id)
                    REFERENCES tasks(id),

                UNIQUE(variant_id, task_id),
                UNIQUE(variant_id, position)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS class_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                variant_id INTEGER NOT NULL,
                class_id INTEGER NOT NULL,
                teacher_id INTEGER NOT NULL,
                assigned_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',

                FOREIGN KEY(variant_id)
                    REFERENCES variants(id),

                FOREIGN KEY(class_id)
                    REFERENCES classes(id),

                FOREIGN KEY(teacher_id)
                    REFERENCES auth_users(id),

                CHECK(status IN ('active', 'closed'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS assignment_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'in_progress',
                started_at TEXT NOT NULL,
                submitted_at TEXT,

                FOREIGN KEY(assignment_id)
                    REFERENCES class_assignments(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(student_id)
                    REFERENCES auth_users(id)
                    ON DELETE CASCADE,

                UNIQUE(assignment_id, student_id),

                CHECK(status IN (
                    'in_progress',
                    'submitted',
                    'reviewed'
                ))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS assignment_answers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                answer TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,

                FOREIGN KEY(attempt_id)
                    REFERENCES assignment_attempts(id)
                    ON DELETE CASCADE,

                FOREIGN KEY(task_id)
                    REFERENCES tasks(id),

                UNIQUE(attempt_id, task_id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_variants_teacher
            ON variants(teacher_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_variants_class
            ON variants(class_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_variant_tasks_variant
            ON variant_tasks(variant_id, position)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_assignments_class
            ON class_assignments(class_id, status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_assignments_teacher
            ON class_assignments(teacher_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attempts_student
            ON assignment_attempts(student_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attempts_assignment
            ON assignment_attempts(assignment_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_assignment_answers_attempt
            ON assignment_answers(attempt_id)
        """)


# =========================================================
# REQUEST MODELS
# =========================================================

class VariantCreate(BaseModel):
    class_id: int = Field(gt=0)

    name: str = Field(
        min_length=2,
        max_length=150
    )

    description: Optional[str] = Field(
        default=None,
        max_length=2000
    )

    task_ids: list[int] = Field(
        min_length=1,
        max_length=100
    )


class VariantUpdate(BaseModel):
    name: Optional[str] = Field(
        default=None,
        min_length=2,
        max_length=150
    )

    description: Optional[str] = Field(
        default=None,
        max_length=2000
    )


class AssignmentCreate(BaseModel):
    variant_id: int = Field(gt=0)


class AnswerSave(BaseModel):
    answer: Any


# =========================================================
# COMMON HELPERS
# =========================================================

def now_iso():
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


def encode_answer(answer: Any) -> str:
    """
    Все ответы сохраняются как JSON.

    Это позволяет отличать строку "123" от числа 123,
    а также сохранять списки и словари.
    """

    try:
        result = json.dumps(
            answer,
            ensure_ascii=False,
            separators=(",", ":")
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="Не удалось обработать формат ответа."
        )

    if len(result) > 50000:
        raise HTTPException(
            status_code=400,
            detail="Ответ слишком большой."
        )

    return result


def decode_answer(value):
    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        # Поддержка ответов, сохранённых старой версией.
        return value


def parse_json(value):
    if value is None:
        return None

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None


def get_teacher_class(conn, class_id, teacher_id):
    class_data = conn.execute(
        """
        SELECT
            c.id,
            c.teacher_id,
            c.name,
            c.subject_code,
            s.name AS subject_name
        FROM classes c
        JOIN subjects s
            ON s.subject_code = c.subject_code
        WHERE c.id = ?
        """,
        (class_id,)
    ).fetchone()

    if class_data is None:
        raise HTTPException(
            status_code=404,
            detail="Класс не найден."
        )

    if class_data["teacher_id"] != teacher_id:
        raise HTTPException(
            status_code=403,
            detail="У вас нет доступа к этому классу."
        )

    return class_data


def get_variant_or_404(conn, variant_id):
    variant = conn.execute(
        """
        SELECT
            v.id,
            v.teacher_id,
            v.class_id,
            v.name,
            v.description,
            v.created_at,
            v.updated_at,
            c.name AS class_name,
            c.subject_code,
            s.name AS subject_name
        FROM variants v
        JOIN classes c
            ON c.id = v.class_id
        JOIN subjects s
            ON s.subject_code = c.subject_code
        WHERE v.id = ?
        """,
        (variant_id,)
    ).fetchone()

    if variant is None:
        raise HTTPException(
            status_code=404,
            detail="Вариант не найден."
        )

    return variant


def get_teacher_variant(conn, variant_id, teacher_id):
    variant = get_variant_or_404(
        conn,
        variant_id
    )

    if variant["teacher_id"] != teacher_id:
        raise HTTPException(
            status_code=403,
            detail="У вас нет доступа к этому варианту."
        )

    return variant


def get_variant_tasks(conn, variant_id):
    rows = conn.execute(
        """
        SELECT
            vt.position,
            t.id,
            t.subject_code,
            t.topic,
            t.question,
            t.difficulty,
            t.task_type,
            t.options_json,
            t.media_json
        FROM variant_tasks vt
        JOIN tasks t
            ON t.id = vt.task_id
        WHERE vt.variant_id = ?
        ORDER BY vt.position
        """,
        (variant_id,)
    ).fetchall()

    return [
        {
            "position": row["position"],
            "id": row["id"],
            "subject_code": row["subject_code"],
            "topic": row["topic"],
            "question": row["question"],
            "difficulty": row["difficulty"],
            "task_type": row["task_type"],
            "options": parse_json(row["options_json"]),
            "media": parse_json(row["media_json"])
        }
        for row in rows
    ]


def serialize_variant(conn, variant):
    tasks = get_variant_tasks(
        conn,
        variant["id"]
    )

    assignments_count = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM class_assignments
        WHERE variant_id = ?
        """,
        (variant["id"],)
    ).fetchone()["total"]

    return {
        "id": variant["id"],
        "teacher_id": variant["teacher_id"],
        "class_id": variant["class_id"],
        "class_name": variant["class_name"],
        "subject_code": variant["subject_code"],
        "subject_name": variant["subject_name"],
        "name": variant["name"],
        "description": variant["description"],
        "tasks_count": len(tasks),
        "assignments_count": assignments_count,
        "tasks": tasks,
        "created_at": variant["created_at"],
        "updated_at": variant["updated_at"]
    }


def get_assignment_or_404(conn, assignment_id):
    assignment = conn.execute(
        """
        SELECT
            a.id,
            a.variant_id,
            a.class_id,
            a.teacher_id,
            a.assigned_at,
            a.status AS assignment_status,

            v.name AS variant_name,
            v.description AS variant_description,

            c.name AS class_name,
            c.subject_code,

            s.name AS subject_name

        FROM class_assignments a

        JOIN variants v
            ON v.id = a.variant_id

        JOIN classes c
            ON c.id = a.class_id

        JOIN subjects s
            ON s.subject_code = c.subject_code

        WHERE a.id = ?
        """,
        (assignment_id,)
    ).fetchone()

    if assignment is None:
        raise HTTPException(
            status_code=404,
            detail="Назначенная работа не найдена."
        )

    return assignment


def ensure_student_in_class(conn, class_id, student_id):
    membership = conn.execute(
        """
        SELECT id
        FROM class_members
        WHERE class_id = ?
          AND student_id = ?
          AND status = 'active'
        """,
        (class_id, student_id)
    ).fetchone()

    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="Вы не состоите в этом классе."
        )


def get_student_attempt(conn, assignment_id, student_id):
    return conn.execute(
        """
        SELECT
            id,
            assignment_id,
            student_id,
            status,
            started_at,
            submitted_at
        FROM assignment_attempts
        WHERE assignment_id = ?
          AND student_id = ?
        """,
        (assignment_id, student_id)
    ).fetchone()


def get_attempt_answers(conn, attempt_id):
    rows = conn.execute(
        """
        SELECT
            task_id,
            answer,
            created_at,
            updated_at
        FROM assignment_answers
        WHERE attempt_id = ?
        ORDER BY task_id
        """,
        (attempt_id,)
    ).fetchall()

    return {
        str(row["task_id"]): {
            "answer": decode_answer(row["answer"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }
        for row in rows
    }


def get_attempt_progress(conn, assignment_id, student_id):
    attempt = get_student_attempt(
        conn,
        assignment_id,
        student_id
    )

    if attempt is None:
        return {
            "attempt": None,
            "answered_count": 0,
            "answers": {}
        }

    answers = get_attempt_answers(
        conn,
        attempt["id"]
    )

    return {
        "attempt": {
            "id": attempt["id"],
            "status": attempt["status"],
            "started_at": attempt["started_at"],
            "submitted_at": attempt["submitted_at"]
        },
        "answered_count": len(answers),
        "answers": answers
    }


def ensure_teacher_assignment(conn, assignment_id, teacher_id):
    assignment = get_assignment_or_404(
        conn,
        assignment_id
    )

    if assignment["teacher_id"] != teacher_id:
        raise HTTPException(
            status_code=403,
            detail="У вас нет доступа к этой работе."
        )

    return assignment


def ensure_student_assignment(conn, assignment_id, student_id):
    assignment = get_assignment_or_404(
        conn,
        assignment_id
    )

    ensure_student_in_class(
        conn,
        assignment["class_id"],
        student_id
    )

    return assignment


def get_attempt_result_summary(conn, attempt_id):
    """
    Возвращает результаты только конкретной назначенной попытки.
    Самостоятельные task_attempts сюда не попадают.
    """

    rows = conn.execute(
        """
        SELECT
            id,
            task_id,
            status,
            is_correct,
            score,
            max_score,
            review_comment,
            reviewed_at
        FROM task_attempts
        WHERE assignment_attempt_id = ?
        ORDER BY task_id
        """,
        (attempt_id,)
    ).fetchall()

    total_score = 0.0
    max_score = 0.0
    pending_review = 0
    checked_count = 0
    task_results = []

    for row in rows:
        score = row["score"]
        maximum = row["max_score"]

        if maximum is not None:
            max_score += float(maximum)

        if score is not None:
            total_score += float(score)

        if row["status"] == "pending_review":
            pending_review += 1

        if row["status"] in ("checked", "reviewed"):
            checked_count += 1

        task_results.append({
            "task_id": row["task_id"],
            "status": row["status"],
            "is_correct": row["is_correct"],
            "score": score,
            "max_score": maximum,
            "review_comment": row["review_comment"],
            "reviewed_at": row["reviewed_at"]
        })

    return {
        "score": round(total_score, 2),
        "max_score": round(max_score, 2),
        "pending_review_count": pending_review,
        "checked_count": checked_count,
        "tasks": task_results
    }


# =========================================================
# CREATE VARIANT
# =========================================================

@router.post("/variants", status_code=201)
def create_variant(
    data: VariantCreate,
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    name = data.name.strip()

    if not name:
        raise HTTPException(
            status_code=400,
            detail="Название варианта не может быть пустым."
        )

    task_ids = data.task_ids

    if len(task_ids) != len(set(task_ids)):
        raise HTTPException(
            status_code=400,
            detail="Вариант не может содержать одинаковые задания."
        )

    description = (
        data.description.strip()
        if data.description and data.description.strip()
        else None
    )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        class_data = get_teacher_class(
            conn,
            data.class_id,
            current_user["id"]
        )

        placeholders = ",".join("?" for _ in task_ids)

        tasks = conn.execute(
            f"""
            SELECT id, subject_code
            FROM tasks
            WHERE id IN ({placeholders})
              AND is_active = 1
            """,
            task_ids
        ).fetchall()

        if len(tasks) != len(task_ids):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Некоторые задания не найдены, "
                    "неактивны или недоступны."
                )
            )

        wrong_subject = [
            task["id"]
            for task in tasks
            if task["subject_code"] != class_data["subject_code"]
        ]

        if wrong_subject:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Все задания варианта должны относиться "
                    "к предмету класса."
                )
            )

        created_at = now_iso()

        cursor = conn.execute(
            """
            INSERT INTO variants (
                teacher_id,
                class_id,
                name,
                description,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                current_user["id"],
                data.class_id,
                name,
                description,
                created_at,
                created_at
            )
        )

        variant_id = cursor.lastrowid

        for position, task_id in enumerate(task_ids, start=1):
            conn.execute(
                """
                INSERT INTO variant_tasks (
                    variant_id,
                    task_id,
                    position
                )
                VALUES (?, ?, ?)
                """,
                (variant_id, task_id, position)
            )

        variant = get_variant_or_404(conn, variant_id)
        result = serialize_variant(conn, variant)

    return {
        "message": "Вариант успешно создан.",
        "variant": result
    }


# =========================================================
# GET TEACHER VARIANTS
# =========================================================

@router.get("/variants")
def get_my_variants(
    class_id: Optional[int] = Query(default=None, gt=0),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    conditions = ["v.teacher_id = ?"]
    params = [current_user["id"]]

    if class_id is not None:
        conditions.append("v.class_id = ?")
        params.append(class_id)

    where_sql = " AND ".join(conditions)

    with get_connection() as conn:
        if class_id is not None:
            get_teacher_class(
                conn,
                class_id,
                current_user["id"]
            )

        total = conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM variants v
            WHERE {where_sql}
            """,
            params
        ).fetchone()["total"]

        rows = conn.execute(
            f"""
            SELECT
                v.id,
                v.teacher_id,
                v.class_id,
                v.name,
                v.description,
                v.created_at,
                v.updated_at,
                c.name AS class_name,
                c.subject_code,
                s.name AS subject_name
            FROM variants v
            JOIN classes c
                ON c.id = v.class_id
            JOIN subjects s
                ON s.subject_code = c.subject_code
            WHERE {where_sql}
            ORDER BY v.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset]
        ).fetchall()

        variants = [
            serialize_variant(conn, row)
            for row in rows
        ]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "variants": variants
    }


# =========================================================
# GET VARIANT
# =========================================================

@router.get("/variants/{variant_id}")
def get_variant(
    variant_id: int,
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        variant = get_teacher_variant(
            conn,
            variant_id,
            current_user["id"]
        )

        result = serialize_variant(conn, variant)

    return {"variant": result}


# =========================================================
# UPDATE VARIANT
# =========================================================

@router.patch("/variants/{variant_id}")
def update_variant(
    variant_id: int,
    data: VariantUpdate,
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    if data.name is None and data.description is None:
        raise HTTPException(
            status_code=400,
            detail="Не указаны данные для изменения."
        )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        get_teacher_variant(
            conn,
            variant_id,
            current_user["id"]
        )

        assignments_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM class_assignments
            WHERE variant_id = ?
            """,
            (variant_id,)
        ).fetchone()["total"]

        if assignments_count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Нельзя изменять вариант, "
                    "который уже назначался классу."
                )
            )

        if data.name is not None:
            name = data.name.strip()

            if not name:
                raise HTTPException(
                    status_code=400,
                    detail="Название не может быть пустым."
                )

            conn.execute(
                """
                UPDATE variants
                SET name = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, now_iso(), variant_id)
            )

        if data.description is not None:
            description = (
                data.description.strip()
                if data.description.strip()
                else None
            )

            conn.execute(
                """
                UPDATE variants
                SET description = ?, updated_at = ?
                WHERE id = ?
                """,
                (description, now_iso(), variant_id)
            )

        variant = get_variant_or_404(conn, variant_id)
        result = serialize_variant(conn, variant)

    return {
        "message": "Вариант обновлён.",
        "variant": result
    }


# =========================================================
# DELETE VARIANT
# =========================================================

@router.delete("/variants/{variant_id}")
def delete_variant(
    variant_id: int,
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        get_teacher_variant(
            conn,
            variant_id,
            current_user["id"]
        )

        assignments_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM class_assignments
            WHERE variant_id = ?
            """,
            (variant_id,)
        ).fetchone()["total"]

        if assignments_count:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Нельзя удалить вариант, "
                    "который уже назначался классу."
                )
            )

        conn.execute(
            "DELETE FROM variants WHERE id = ?",
            (variant_id,)
        )

    return {
        "message": "Вариант удалён.",
        "variant_id": variant_id
    }


# =========================================================
# ASSIGN VARIANT TO CLASS
# =========================================================

@router.post("/assignments", status_code=201)
def assign_variant(
    data: AssignmentCreate,
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        variant = get_teacher_variant(
            conn,
            data.variant_id,
            current_user["id"]
        )

        get_teacher_class(
            conn,
            variant["class_id"],
            current_user["id"]
        )

        task_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM variant_tasks
            WHERE variant_id = ?
            """,
            (data.variant_id,)
        ).fetchone()["total"]

        if task_count == 0:
            raise HTTPException(
                status_code=400,
                detail="Нельзя назначить пустой вариант."
            )

        assigned_at = now_iso()

        cursor = conn.execute(
            """
            INSERT INTO class_assignments (
                variant_id,
                class_id,
                teacher_id,
                assigned_at,
                status
            )
            VALUES (?, ?, ?, ?, 'active')
            """,
            (
                data.variant_id,
                variant["class_id"],
                current_user["id"],
                assigned_at
            )
        )

        assignment = get_assignment_or_404(
            conn,
            cursor.lastrowid
        )

    return {
        "message": "Вариант назначен классу.",
        "assignment": {
            "id": assignment["id"],
            "variant_id": assignment["variant_id"],
            "variant_name": assignment["variant_name"],
            "class_id": assignment["class_id"],
            "class_name": assignment["class_name"],
            "subject_code": assignment["subject_code"],
            "subject_name": assignment["subject_name"],
            "assigned_at": assignment["assigned_at"],
            "status": assignment["assignment_status"]
        }
    }


# =========================================================
# GET ASSIGNMENTS
# =========================================================

@router.get("/assignments")
def get_assignments(
    class_id: Optional[int] = Query(default=None, gt=0),
    status: Optional[str] = Query(
        default=None,
        pattern="^(active|closed)$"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user["id"]

    with get_connection() as conn:

        if current_user["role"] == "teacher":
            conditions = ["a.teacher_id = ?"]
            params = [user_id]

            if class_id is not None:
                get_teacher_class(conn, class_id, user_id)
                conditions.append("a.class_id = ?")
                params.append(class_id)

            if status is not None:
                conditions.append("a.status = ?")
                params.append(status)

            where_sql = " AND ".join(conditions)

            total = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM class_assignments a
                WHERE {where_sql}
                """,
                params
            ).fetchone()["total"]

            rows = conn.execute(
                f"""
                SELECT
                    a.id,
                    a.variant_id,
                    a.class_id,
                    a.assigned_at,
                    a.status,
                    v.name AS variant_name,
                    c.name AS class_name,
                    c.subject_code,
                    s.name AS subject_name,

                    (
                        SELECT COUNT(*)
                        FROM assignment_attempts aa
                        WHERE aa.assignment_id = a.id
                    ) AS attempts_count,

                    (
                        SELECT COUNT(*)
                        FROM assignment_attempts aa
                        WHERE aa.assignment_id = a.id
                          AND aa.status IN ('submitted', 'reviewed')
                    ) AS submitted_count

                FROM class_assignments a
                JOIN variants v ON v.id = a.variant_id
                JOIN classes c ON c.id = a.class_id
                JOIN subjects s ON s.subject_code = c.subject_code

                WHERE {where_sql}
                ORDER BY a.id DESC
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset]
            ).fetchall()

            items = [
                {
                    "id": row["id"],
                    "variant_id": row["variant_id"],
                    "variant_name": row["variant_name"],
                    "class_id": row["class_id"],
                    "class_name": row["class_name"],
                    "subject_code": row["subject_code"],
                    "subject_name": row["subject_name"],
                    "assigned_at": row["assigned_at"],
                    "status": row["status"],
                    "attempts_count": row["attempts_count"],
                    "submitted_count": row["submitted_count"]
                }
                for row in rows
            ]

        elif current_user["role"] == "student":
            conditions = [
                "cm.student_id = ?",
                "cm.status = 'active'",
                "a.status = 'active'"
            ]

            params = [user_id]

            if class_id is not None:
                conditions.append("a.class_id = ?")
                params.append(class_id)

            where_sql = " AND ".join(conditions)

            total = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM class_assignments a
                JOIN class_members cm
                    ON cm.class_id = a.class_id
                WHERE {where_sql}
                """,
                params
            ).fetchone()[0]

            rows = conn.execute(
                f"""
                SELECT
                    a.id,
                    a.variant_id,
                    a.class_id,
                    a.assigned_at,
                    a.status,
                    v.name AS variant_name,
                    c.name AS class_name,
                    c.subject_code,
                    s.name AS subject_name,

                    aa.id AS attempt_id,
                    aa.status AS attempt_status,
                    aa.started_at,
                    aa.submitted_at,

                    (
                        SELECT COUNT(*)
                        FROM variant_tasks vt
                        WHERE vt.variant_id = a.variant_id
                    ) AS tasks_count,

                    (
                        SELECT COUNT(*)
                        FROM assignment_answers ans
                        WHERE ans.attempt_id = aa.id
                    ) AS answered_count

                FROM class_assignments a

                JOIN class_members cm
                    ON cm.class_id = a.class_id

                JOIN variants v
                    ON v.id = a.variant_id

                JOIN classes c
                    ON c.id = a.class_id

                JOIN subjects s
                    ON s.subject_code = c.subject_code

                LEFT JOIN assignment_attempts aa
                    ON aa.assignment_id = a.id
                   AND aa.student_id = ?

                WHERE {where_sql}

                ORDER BY a.id DESC
                LIMIT ? OFFSET ?
                """,
                [user_id] + params + [limit, offset]
            ).fetchall()

            items = [
                {
                    "id": row["id"],
                    "variant_id": row["variant_id"],
                    "variant_name": row["variant_name"],
                    "class_id": row["class_id"],
                    "class_name": row["class_name"],
                    "subject_code": row["subject_code"],
                    "subject_name": row["subject_name"],
                    "assigned_at": row["assigned_at"],
                    "status": row["status"],
                    "tasks_count": row["tasks_count"],
                    "attempt": {
                        "id": row["attempt_id"],
                        "status": row["attempt_status"],
                        "started_at": row["started_at"],
                        "submitted_at": row["submitted_at"],
                        "answered_count": row["answered_count"]
                    } if row["attempt_id"] else None
                }
                for row in rows
            ]

        else:
            raise HTTPException(
                status_code=403,
                detail="Доступ запрещён."
            )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "assignments": items
    }


# =========================================================
# GET ASSIGNMENT DETAILS AND PROGRESS
# =========================================================

@router.get("/assignments/{assignment_id}")
def get_assignment(
    assignment_id: int,
    current_user: dict = Depends(get_current_user)
):
    with get_connection() as conn:
        assignment = get_assignment_or_404(
            conn,
            assignment_id
        )

        if current_user["role"] == "teacher":
            if assignment["teacher_id"] != current_user["id"]:
                raise HTTPException(
                    status_code=403,
                    detail="У вас нет доступа к этой работе."
                )

            return {
                "assignment": {
                    "id": assignment["id"],
                    "variant_id": assignment["variant_id"],
                    "variant_name": assignment["variant_name"],
                    "class_id": assignment["class_id"],
                    "class_name": assignment["class_name"],
                    "subject_code": assignment["subject_code"],
                    "subject_name": assignment["subject_name"],
                    "assigned_at": assignment["assigned_at"],
                    "status": assignment["assignment_status"]
                },
                "tasks": get_variant_tasks(
                    conn,
                    assignment["variant_id"]
                )
            }

        if current_user["role"] == "student":
            ensure_student_in_class(
                conn,
                assignment["class_id"],
                current_user["id"]
            )

            return {
                "assignment": {
                    "id": assignment["id"],
                    "variant_id": assignment["variant_id"],
                    "variant_name": assignment["variant_name"],
                    "class_id": assignment["class_id"],
                    "class_name": assignment["class_name"],
                    "subject_code": assignment["subject_code"],
                    "subject_name": assignment["subject_name"],
                    "assigned_at": assignment["assigned_at"],
                    "status": assignment["assignment_status"]
                },
                "tasks": get_variant_tasks(
                    conn,
                    assignment["variant_id"]
                ),
                "progress": get_attempt_progress(
                    conn,
                    assignment_id,
                    current_user["id"]
                )
            }

        raise HTTPException(
            status_code=403,
            detail="Доступ запрещён."
        )


# =========================================================
# START OR RESUME ATTEMPT
# =========================================================

@router.post("/assignments/{assignment_id}/start")
def start_assignment(
    assignment_id: int,
    current_user: dict = Depends(get_current_user)
):
    require_student(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        assignment = ensure_student_assignment(
            conn,
            assignment_id,
            current_user["id"]
        )

        attempt = get_student_attempt(
            conn,
            assignment_id,
            current_user["id"]
        )

        if attempt is None:
            if assignment["assignment_status"] != "active":
                raise HTTPException(
                    status_code=409,
                    detail="Эта работа больше недоступна для новых попыток."
                )

            conn.execute(
                """
                INSERT INTO assignment_attempts (
                    assignment_id,
                    student_id,
                    status,
                    started_at,
                    submitted_at
                )
                VALUES (?, ?, 'in_progress', ?, NULL)
                """,
                (
                    assignment_id,
                    current_user["id"],
                    now_iso()
                )
            )

        elif attempt["status"] in ("submitted", "reviewed"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Вы уже завершили эту работу. "
                    "Повторное выполнение запрещено."
                )
            )

        progress = get_attempt_progress(
            conn,
            assignment_id,
            current_user["id"]
        )

    return {
        "message": (
            "Работа начата."
            if progress["answered_count"] == 0
            else "Сохранённый прогресс восстановлен."
        ),
        "attempt": progress["attempt"],
        "answered_count": progress["answered_count"],
        "answers": progress["answers"]
    }


# =========================================================
# SAVE ANSWER
# =========================================================

@router.put("/assignments/{assignment_id}/answers/{task_id}")
def save_assignment_answer(
    assignment_id: int,
    task_id: int,
    data: AnswerSave,
    current_user: dict = Depends(get_current_user)
):
    require_student(current_user)

    encoded_answer = encode_answer(data.answer)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        assignment = ensure_student_assignment(
            conn,
            assignment_id,
            current_user["id"]
        )

        attempt = get_student_attempt(
            conn,
            assignment_id,
            current_user["id"]
        )

        if attempt is None:
            raise HTTPException(
                status_code=409,
                detail="Сначала необходимо начать выполнение работы."
            )

        if attempt["status"] != "in_progress":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Работа уже отправлена. "
                    "Изменять ответы нельзя."
                )
            )

        task_in_variant = conn.execute(
            """
            SELECT 1
            FROM variant_tasks
            WHERE variant_id = ?
              AND task_id = ?
            """,
            (assignment["variant_id"], task_id)
        ).fetchone()

        if task_in_variant is None:
            raise HTTPException(
                status_code=404,
                detail="Это задание не входит в назначенный вариант."
            )

        timestamp = now_iso()

        conn.execute(
            """
            INSERT INTO assignment_answers (
                attempt_id,
                task_id,
                answer,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?)

            ON CONFLICT(attempt_id, task_id)
            DO UPDATE SET
                answer = excluded.answer,
                updated_at = excluded.updated_at
            """,
            (
                attempt["id"],
                task_id,
                encoded_answer,
                timestamp,
                timestamp
            )
        )

        answered_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM assignment_answers
            WHERE attempt_id = ?
            """,
            (attempt["id"],)
        ).fetchone()["total"]

        tasks_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM variant_tasks
            WHERE variant_id = ?
            """,
            (assignment["variant_id"],)
        ).fetchone()["total"]

    return {
        "message": "Ответ сохранён.",
        "assignment_id": assignment_id,
        "task_id": task_id,
        "answered_count": answered_count,
        "tasks_count": tasks_count,
        "progress_percent": round(
            answered_count / tasks_count * 100,
            2
        ) if tasks_count else 0
    }


# =========================================================
# SUBMIT ASSIGNMENT
# =========================================================

@router.post("/assignments/{assignment_id}/submit")
def submit_assignment(
    assignment_id: int,
    current_user: dict = Depends(get_current_user)
):
    require_student(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        assignment = ensure_student_assignment(
            conn,
            assignment_id,
            current_user["id"]
        )

        attempt = get_student_attempt(
            conn,
            assignment_id,
            current_user["id"]
        )

        if attempt is None:
            raise HTTPException(
                status_code=409,
                detail="Вы ещё не начинали выполнение этой работы."
            )

        if attempt["status"] != "in_progress":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Эта работа уже отправлена. "
                    "Повторная отправка запрещена."
                )
            )

        tasks = conn.execute(
            """
            SELECT task_id
            FROM variant_tasks
            WHERE variant_id = ?
            ORDER BY position
            """,
            (assignment["variant_id"],)
        ).fetchall()

        answered = conn.execute(
            """
            SELECT task_id
            FROM assignment_answers
            WHERE attempt_id = ?
            """,
            (attempt["id"],)
        ).fetchall()

        answered_ids = {
            row["task_id"]
            for row in answered
        }

        missing_tasks = [
            row["task_id"]
            for row in tasks
            if row["task_id"] not in answered_ids
        ]

        if missing_tasks:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": (
                        "Нельзя завершить вариант: "
                        "не на все задания сохранены ответы."
                    ),
                    "missing_task_ids": missing_tasks,
                    "missing_count": len(missing_tasks)
                }
            )

        submitted_at = now_iso()

        # Проверка всех сохранённых ответов.
        # Функция находится в checking_routes.py.
        grading_result = grade_assignment_attempt(
            conn=conn,
            assignment_attempt_id=attempt["id"],
            user_id=current_user["id"],
            now=submitted_at
        )

        cursor = conn.execute(
            """
            UPDATE assignment_attempts
            SET status = 'submitted',
                submitted_at = ?
            WHERE id = ?
              AND status = 'in_progress'
            """,
            (
                submitted_at,
                attempt["id"]
            )
        )

        if cursor.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Работа уже была отправлена."
            )

        result_summary = get_attempt_result_summary(
            conn,
            attempt["id"]
        )

    return {
        "message": "Работа успешно отправлена и передана на проверку.",
        "assignment_id": assignment_id,
        "attempt_id": attempt["id"],
        "status": "submitted",
        "submitted_at": submitted_at,
        "answered_count": len(answered_ids),
        "tasks_count": len(tasks),
        "grading": {
            "score": result_summary["score"],
            "max_score": result_summary["max_score"],
            "checked_count": result_summary["checked_count"],
            "pending_review_count": result_summary["pending_review_count"]
        }
    }


# =========================================================
# TEACHER: ASSIGNMENT RESULTS
# =========================================================

@router.get("/assignments/{assignment_id}/results")
def get_assignment_results(
    assignment_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        assignment = ensure_teacher_assignment(
            conn,
            assignment_id,
            current_user["id"]
        )

        total_students = conn.execute(
            """
            SELECT COUNT(DISTINCT cm.student_id) AS total
            FROM class_members cm
            LEFT JOIN assignment_attempts aa
                ON aa.assignment_id = ?
               AND aa.student_id = cm.student_id
            WHERE cm.class_id = ?
              AND (cm.status = 'active' OR aa.id IS NOT NULL)
            """,
            (assignment_id, assignment["class_id"])
        ).fetchone()["total"]

        rows = conn.execute(
            """
            SELECT
                u.id AS student_id,
                u.username,
                u.email,

                aa.id AS attempt_id,
                aa.status AS attempt_status,
                aa.started_at,
                aa.submitted_at,

                (
                    SELECT COUNT(*)
                    FROM assignment_answers ans
                    WHERE ans.attempt_id = aa.id
                ) AS answered_count

            FROM class_members cm

            JOIN auth_users u
                ON u.id = cm.student_id

            LEFT JOIN assignment_attempts aa
                ON aa.assignment_id = ?
               AND aa.student_id = u.id

            WHERE cm.class_id = ?
              AND (cm.status = 'active' OR aa.id IS NOT NULL)

            ORDER BY u.username COLLATE NOCASE

            LIMIT ? OFFSET ?
            """,
            (
                assignment_id,
                assignment["class_id"],
                limit,
                offset
            )
        ).fetchall()

        tasks_count = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM variant_tasks
            WHERE variant_id = ?
            """,
            (assignment["variant_id"],)
        ).fetchone()["total"]

        students = []

        submitted_count = 0
        in_progress_count = 0

        for row in rows:
            attempt_data = None

            if row["attempt_id"]:
                result_summary = get_attempt_result_summary(
                    conn,
                    row["attempt_id"]
                )

                if row["attempt_status"] in ("submitted", "reviewed"):
                    submitted_count += 1
                elif row["attempt_status"] == "in_progress":
                    in_progress_count += 1

                attempt_data = {
                    "id": row["attempt_id"],
                    "status": row["attempt_status"],
                    "started_at": row["started_at"],
                    "submitted_at": row["submitted_at"],
                    "answered_count": row["answered_count"],
                    "tasks_count": tasks_count,
                    "score": result_summary["score"],
                    "max_score": result_summary["max_score"],
                    "pending_review_count": result_summary[
                        "pending_review_count"
                    ],
                    "checked_count": result_summary["checked_count"],
                    "task_results": result_summary["tasks"]
                }

            students.append({
                "student_id": row["student_id"],
                "username": row["username"],
                "email": row["email"],
                "attempt": attempt_data
            })

    return {
        "assignment": {
            "id": assignment["id"],
            "variant_id": assignment["variant_id"],
            "variant_name": assignment["variant_name"],
            "class_id": assignment["class_id"],
            "class_name": assignment["class_name"],
            "subject_code": assignment["subject_code"],
            "subject_name": assignment["subject_name"],
            "assigned_at": assignment["assigned_at"],
            "status": assignment["assignment_status"]
        },

        "statistics": {
            "total_students": total_students,
            "started_count": submitted_count + in_progress_count,
            "in_progress_count": in_progress_count,
            "submitted_count": submitted_count,
            "not_started_count": max(
                0,
                total_students - submitted_count - in_progress_count
            )
        },

        "limit": limit,
        "offset": offset,
        "students": students
    }


# =========================================================
# CLOSE ASSIGNMENT
# =========================================================

@router.post("/assignments/{assignment_id}/close")
def close_assignment(
    assignment_id: int,
    current_user: dict = Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        ensure_teacher_assignment(
            conn,
            assignment_id,
            current_user["id"]
        )

        cursor = conn.execute(
            """
            UPDATE class_assignments
            SET status = 'closed'
            WHERE id = ?
              AND status = 'active'
            """,
            (assignment_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=409,
                detail="Работа уже закрыта."
            )

    return {
        "message": "Назначенная работа закрыта.",
        "assignment_id": assignment_id,
        "status": "closed"
    }


# =========================================================
# INITIALIZATION
# =========================================================

init_variants_tables()