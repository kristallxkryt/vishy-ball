
import json
import sqlite3

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_routes import require_admin


router = APIRouter(prefix="/api/admin", tags=["Администрирование"])
DB_PATH = Path(__file__).resolve().parent / "users.db"

Difficulty = Literal["easy", "medium", "hard"]
TaskType = Literal[
    "text",
    "single_choice",
    "multiple_choice",
    "matching",
    "ordering",
    "long_text",
]


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


def init_admin_catalog_db():
    """Создаёт каталог и безопасно добавляет новые поля заданий."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_code TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(subject_code, name)
            )
        """)

        table_exists = conn.execute("""
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'tasks'
        """).fetchone()

        if table_exists:
            columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(tasks)"
                ).fetchall()
            }

            migrations = {
                "task_type": "TEXT NOT NULL DEFAULT 'text'",
                "options_json": "TEXT NOT NULL DEFAULT '[]'",
                "media_json": "TEXT NOT NULL DEFAULT '[]'",
                "checking_config_json": "TEXT NOT NULL DEFAULT '{}'",
            }

            for name, definition in migrations.items():
                if name not in columns:
                    conn.execute(
                        f"ALTER TABLE tasks ADD COLUMN {name} {definition}"
                    )


init_admin_catalog_db()


# =========================================================
# PYDANTIC MODELS
# =========================================================

class TaskCreate(BaseModel):
    subject_code: str = Field(min_length=2, max_length=50)
    topic: str = Field(min_length=1, max_length=150)
    question: str = Field(min_length=1, max_length=20000)
    answer: str | None = Field(default=None, max_length=10000)
    hint: str | None = Field(default=None, max_length=10000)
    explanation: str | None = Field(default=None, max_length=20000)
    difficulty: Difficulty = "medium"
    source: str | None = Field(default=None, max_length=500)

    task_type: TaskType = "text"
    options: list[dict[str, Any]] = Field(default_factory=list)
    media: list[dict[str, Any]] = Field(default_factory=list)
    checking_config: dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    subject_code: str | None = Field(
        default=None, min_length=2, max_length=50
    )
    topic: str | None = Field(
        default=None, min_length=1, max_length=150
    )
    question: str | None = Field(
        default=None, min_length=1, max_length=20000
    )
    answer: str | None = Field(default=None, max_length=10000)
    hint: str | None = Field(default=None, max_length=10000)
    explanation: str | None = Field(default=None, max_length=20000)
    difficulty: Difficulty | None = None
    source: str | None = Field(default=None, max_length=500)

    task_type: TaskType | None = None
    options: list[dict[str, Any]] | None = None
    media: list[dict[str, Any]] | None = None
    checking_config: dict[str, Any] | None = None


class SubjectCreate(BaseModel):
    subject_code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=2, max_length=150)
    sort_order: int = Field(default=0, ge=0)


class SubjectUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=2, max_length=150
    )
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class TopicCreate(BaseModel):
    subject_code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=150)
    description: str | None = Field(default=None, max_length=5000)
    sort_order: int = Field(default=0, ge=0)


class TopicUpdate(BaseModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=150
    )
    description: str | None = Field(default=None, max_length=5000)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


# =========================================================
# SERIALIZATION AND VALIDATION
# =========================================================

def _load_json(value: str | None, fallback: Any):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def task_to_admin(row):
    keys = set(row.keys())

    return {
        "id": row["id"],
        "subject_code": row["subject_code"],
        "topic": row["topic"],
        "question": row["question"],
        "answer": row["answer"],
        "hint": row["hint"],
        "explanation": row["explanation"],
        "difficulty": row["difficulty"],
        "source": row["source"],
        "task_type": (
            row["task_type"] if "task_type" in keys else "text"
        ),
        "options": (
            _load_json(row["options_json"], [])
            if "options_json" in keys else []
        ),
        "media": (
            _load_json(row["media_json"], [])
            if "media_json" in keys else []
        ),
        "checking_config": (
            _load_json(row["checking_config_json"], {})
            if "checking_config_json" in keys else {}
        ),
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


def validate_task_fields(task_type, answer, options, checking_config):
    if task_type == "text" and not (answer or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Для текстового задания необходимо указать правильный ответ.",
        )

    if task_type in {
        "single_choice",
        "multiple_choice",
        "matching",
        "ordering",
    }:
        if not options:
            raise HTTPException(
                status_code=400,
                detail="Для этого типа задания необходимо добавить варианты.",
            )

        if not checking_config:
            raise HTTPException(
                status_code=400,
                detail="Не задана конфигурация правильного ответа.",
            )


def subject_to_admin(row):
    return {
        "id": row["id"],
        "subject_code": row["subject_code"],
        "name": row["name"],
        "is_active": bool(row["is_active"]),
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "topic_count": row["topic_count"],
        "task_count": row["task_count"],
    }


def topic_to_admin(row):
    return {
        "id": row["id"],
        "subject_code": row["subject_code"],
        "name": row["name"],
        "description": row["description"],
        "is_active": bool(row["is_active"]),
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "task_count": row["task_count"],
    }


# =========================================================
# TASK MANAGEMENT
# =========================================================

@router.post("/tasks", dependencies=[Depends(require_admin)])
def create_task(data: TaskCreate):
    subject_code = data.subject_code.strip()
    topic_name = data.topic.strip()
    question = data.question.strip()
    answer = (data.answer or "").strip()

    if not subject_code or not topic_name or not question:
        raise HTTPException(
            status_code=400,
            detail="Предмет, тема и условие обязательны."
        )

    validate_task_fields(
        data.task_type,
        answer,
        data.options,
        data.checking_config
    )

    with get_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO tasks (
                subject_code, topic, question, answer,
                hint, explanation, difficulty, source,
                task_type, options_json, media_json,
                checking_config_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            subject_code,
            topic_name,
            question,
            answer,
            data.hint,
            data.explanation,
            data.difficulty,
            data.source,
            data.task_type,
            json.dumps(data.options, ensure_ascii=False),
            json.dumps(data.media, ensure_ascii=False),
            json.dumps(data.checking_config, ensure_ascii=False),
        ))

        task_id = cursor.lastrowid

        conn.execute(
            """
            INSERT OR IGNORE INTO topics (subject_code, name)
            VALUES (?, ?)
            """,
            (subject_code, topic_name),
        )

        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

    return {
        "message": "Задание успешно добавлено.",
        "task": task_to_admin(row)
    }


@router.get("/tasks", dependencies=[Depends(require_admin)])
def get_all_tasks(
    subject_code: str | None = None,
    include_inactive: bool = False
):
    query = "SELECT * FROM tasks WHERE 1 = 1"
    params = []

    if not include_inactive:
        query += " AND is_active = 1"

    if subject_code:
        query += " AND subject_code = ?"
        params.append(subject_code)

    query += " ORDER BY id DESC"

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return {
        "total": len(rows),
        "tasks": [task_to_admin(row) for row in rows]
    }


@router.get("/tasks/{task_id}", dependencies=[Depends(require_admin)])
def get_admin_task(task_id: int):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Задание не найдено."
        )

    return task_to_admin(row)


@router.patch("/tasks/{task_id}", dependencies=[Depends(require_admin)])
def update_task(task_id: int, data: TaskUpdate):
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Не передано ни одного поля для изменения."
        )

    for key in ("subject_code", "topic", "question"):
        if key in updates:
            if updates[key] is None or not updates[key].strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"Поле {key} не может быть пустым."
                )

            updates[key] = updates[key].strip()

    if "answer" in updates:
        updates["answer"] = (updates["answer"] or "").strip()

    for key in ("task_type", "options", "media", "checking_config"):
        if key in updates and updates[key] is None:
            raise HTTPException(
                status_code=400,
                detail=f"Поле {key} не может быть null."
            )

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

        if existing is None:
            raise HTTPException(
                status_code=404,
                detail="Задание не найдено."
            )

        current_type = updates.get(
            "task_type", existing["task_type"]
        )
        current_answer = updates.get(
            "answer", existing["answer"]
        )
        current_options = updates.get(
            "options",
            _load_json(existing["options_json"], [])
        )
        current_config = updates.get(
            "checking_config",
            _load_json(existing["checking_config_json"], {})
        )

        validate_task_fields(
            current_type,
            current_answer,
            current_options,
            current_config
        )

        db_updates = {}

        regular_fields = {
            "subject_code", "topic", "question", "answer",
            "hint", "explanation", "difficulty", "source",
            "task_type",
        }

        for key in regular_fields:
            if key in updates:
                db_updates[key] = updates[key]

        json_columns = {
            "options": "options_json",
            "media": "media_json",
            "checking_config": "checking_config_json",
        }

        for key, column in json_columns.items():
            if key in updates:
                db_updates[column] = json.dumps(
                    updates[key],
                    ensure_ascii=False
                )

        if not db_updates:
            raise HTTPException(
                status_code=400,
                detail="Нет допустимых полей для изменения."
            )

        fields = list(db_updates)
        set_clause = ", ".join(
            f"{field} = ?" for field in fields
        )

        values = [
            db_updates[field] for field in fields
        ] + [task_id]

        conn.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?",
            values
        )

        if "subject_code" in updates or "topic" in updates:
            row_data = conn.execute(
                """
                SELECT subject_code, topic
                FROM tasks WHERE id = ?
                """,
                (task_id,)
            ).fetchone()

            conn.execute(
                """
                INSERT OR IGNORE INTO topics (subject_code, name)
                VALUES (?, ?)
                """,
                (row_data["subject_code"], row_data["topic"]),
            )

        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (task_id,)
        ).fetchone()

    return {
        "message": "Задание обновлено.",
        "task": task_to_admin(row)
    }


@router.delete("/tasks/{task_id}", dependencies=[Depends(require_admin)])
def deactivate_task(task_id: int):
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE tasks SET is_active = 0 WHERE id = ?",
            (task_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Задание не найдено."
            )

    return {
        "message": "Задание отключено.",
        "task_id": task_id
    }


# =========================================================
# SUBJECT MANAGEMENT
# =========================================================

@router.get("/subjects", dependencies=[Depends(require_admin)])
def get_admin_subjects(include_inactive: bool = False):
    query = """
        SELECT s.*,
            (
                SELECT COUNT(*) FROM topics tp
                WHERE tp.subject_code = s.subject_code
                  AND tp.is_active = 1
            ) AS topic_count,
            (
                SELECT COUNT(*) FROM tasks t
                WHERE t.subject_code = s.subject_code
                  AND t.is_active = 1
            ) AS task_count
        FROM subjects s
    """

    if not include_inactive:
        query += " WHERE s.is_active = 1"

    query += " ORDER BY s.sort_order, s.name"

    with get_connection() as conn:
        rows = conn.execute(query).fetchall()

    return {
        "total": len(rows),
        "subjects": [subject_to_admin(row) for row in rows]
    }


@router.post("/subjects", dependencies=[Depends(require_admin)])
def create_subject(data: SubjectCreate):
    subject_code = data.subject_code.strip()
    name = data.name.strip()

    if not subject_code or not name:
        raise HTTPException(
            status_code=400,
            detail="Код и название предмета не могут быть пустыми."
        )

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO subjects (subject_code, name, sort_order)
                VALUES (?, ?, ?)
                """,
                (subject_code, name, data.sort_order),
            )

            row = conn.execute(
                """
                SELECT s.*, 0 AS topic_count, 0 AS task_count
                FROM subjects s WHERE s.id = ?
                """,
                (cursor.lastrowid,)
            ).fetchone()

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Предмет с таким кодом уже существует."
        )

    return {
        "message": "Предмет успешно добавлен.",
        "subject": subject_to_admin(row)
    }


@router.patch(
    "/subjects/{subject_code}",
    dependencies=[Depends(require_admin)]
)
def update_subject(subject_code: str, data: SubjectUpdate):
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Не передано ни одного поля для изменения."
        )

    if "name" in updates:
        if updates["name"] is None or not updates["name"].strip():
            raise HTTPException(
                status_code=400,
                detail="Название предмета не может быть пустым."
            )

        updates["name"] = updates["name"].strip()

    fields = list(updates)
    set_clause = ", ".join(
        f"{field} = ?" for field in fields
    )

    values = [
        int(updates[f]) if f == "is_active" else updates[f]
        for f in fields
    ]
    values.append(subject_code)

    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM subjects WHERE subject_code = ?",
            (subject_code,)
        ).fetchone()

        if exists is None:
            raise HTTPException(
                status_code=404,
                detail="Предмет не найден."
            )

        conn.execute(
            f"UPDATE subjects SET {set_clause} WHERE subject_code = ?",
            values
        )

        row = conn.execute(
            """
            SELECT s.*,
                (
                    SELECT COUNT(*) FROM topics tp
                    WHERE tp.subject_code = s.subject_code
                      AND tp.is_active = 1
                ) AS topic_count,
                (
                    SELECT COUNT(*) FROM tasks t
                    WHERE t.subject_code = s.subject_code
                      AND t.is_active = 1
                ) AS task_count
            FROM subjects s
            WHERE s.subject_code = ?
            """,
            (subject_code,)
        ).fetchone()

    return {
        "message": "Предмет обновлён.",
        "subject": subject_to_admin(row)
    }


@router.delete(
    "/subjects/{subject_code}",
    dependencies=[Depends(require_admin)]
)
def deactivate_subject(subject_code: str):
    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE subjects SET is_active = 0
            WHERE subject_code = ?
            """,
            (subject_code,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Предмет не найден."
            )

    return {
        "message": "Предмет отключён.",
        "subject_code": subject_code
    }


# =========================================================
# TOPIC MANAGEMENT
# =========================================================

@router.get("/topics", dependencies=[Depends(require_admin)])
def get_admin_topics(
    subject_code: str | None = None,
    include_inactive: bool = False
):
    where = []
    params = []

    if not include_inactive:
        where.append("tp.is_active = 1")

    if subject_code:
        where.append("tp.subject_code = ?")
        params.append(subject_code)

    query = """
        SELECT tp.*, COUNT(DISTINCT t.id) AS task_count
        FROM topics tp
        LEFT JOIN tasks t
            ON t.subject_code = tp.subject_code
            AND t.topic = tp.name
            AND t.is_active = 1
    """

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " GROUP BY tp.id ORDER BY tp.sort_order, tp.name"

    with get_connection() as conn:
        catalog_rows = conn.execute(
            query, params
        ).fetchall()

        legacy_query = """
            SELECT
                t.subject_code,
                t.topic AS name,
                COUNT(DISTINCT t.id) AS task_count
            FROM tasks t
            WHERE t.is_active = 1
              AND NOT EXISTS (
                  SELECT 1 FROM topics tp
                  WHERE tp.subject_code = t.subject_code
                    AND tp.name = t.topic
              )
        """

        legacy_params = []

        if subject_code:
            legacy_query += " AND t.subject_code = ?"
            legacy_params.append(subject_code)

        legacy_query += """
            GROUP BY t.subject_code, t.topic
            ORDER BY t.subject_code, t.topic
        """

        legacy_rows = conn.execute(
            legacy_query, legacy_params
        ).fetchall()

    topics = [
        topic_to_admin(row) for row in catalog_rows
    ]

    for row in legacy_rows:
        topics.append({
            "id": None,
            "subject_code": row["subject_code"],
            "name": row["name"],
            "description": None,
            "is_active": True,
            "sort_order": 0,
            "created_at": None,
            "task_count": row["task_count"],
        })

    return {
        "total": len(topics),
        "topics": topics
    }


@router.post("/topics", dependencies=[Depends(require_admin)])
def create_topic(data: TopicCreate):
    subject_code = data.subject_code.strip()
    name = data.name.strip()

    if not subject_code or not name:
        raise HTTPException(
            status_code=400,
            detail="Предмет и название темы не могут быть пустыми."
        )

    try:
        with get_connection() as conn:
            subject = conn.execute(
                """
                SELECT subject_code FROM subjects
                WHERE subject_code = ? AND is_active = 1
                """,
                (subject_code,)
            ).fetchone()

            if subject is None:
                raise HTTPException(
                    status_code=404,
                    detail="Активный предмет не найден."
                )

            cursor = conn.execute(
                """
                INSERT INTO topics (
                    subject_code, name, description, sort_order
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    subject_code,
                    name,
                    data.description,
                    data.sort_order
                )
            )

            row = conn.execute(
                """
                SELECT tp.*, 0 AS task_count
                FROM topics tp WHERE tp.id = ?
                """,
                (cursor.lastrowid,)
            ).fetchone()

    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Такая тема уже существует у этого предмета."
        )

    return {
        "message": "Тема успешно добавлена.",
        "topic": topic_to_admin(row)
    }


@router.patch(
    "/topics/{topic_id}",
    dependencies=[Depends(require_admin)]
)
def update_topic(topic_id: int, data: TopicUpdate):
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=400,
            detail="Не передано ни одного поля для изменения."
        )

    if "name" in updates:
        if updates["name"] is None or not updates["name"].strip():
            raise HTTPException(
                status_code=400,
                detail="Название темы не может быть пустым."
            )

        updates["name"] = updates["name"].strip()

    if "description" in updates and updates["description"] is not None:
        updates["description"] = updates["description"].strip()

    fields = list(updates)
    set_clause = ", ".join(
        f"{field} = ?" for field in fields
    )

    values = [
        int(updates[f]) if f == "is_active" else updates[f]
        for f in fields
    ]
    values.append(topic_id)

    with get_connection() as conn:
        old_topic = conn.execute(
            """
            SELECT subject_code, name
            FROM topics WHERE id = ?
            """,
            (topic_id,)
        ).fetchone()

        if old_topic is None:
            raise HTTPException(
                status_code=404,
                detail="Тема не найдена."
            )

        try:
            conn.execute(
                f"UPDATE topics SET {set_clause} WHERE id = ?",
                values
            )

            if "name" in updates:
                conn.execute(
                    """
                    UPDATE tasks SET topic = ?
                    WHERE subject_code = ? AND topic = ?
                    """,
                    (
                        updates["name"],
                        old_topic["subject_code"],
                        old_topic["name"]
                    )
                )

                progress_table = conn.execute(
                    """
                    SELECT 1 FROM sqlite_master
                    WHERE type = 'table' AND name = 'user_progress'
                    """
                ).fetchone()

                if progress_table:
                    conn.execute(
                        """
                        UPDATE user_progress SET topic = ?
                        WHERE subject_code = ? AND topic = ?
                        """,
                        (
                            updates["name"],
                            old_topic["subject_code"],
                            old_topic["name"]
                        )
                    )

        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409,
                detail="Тема с таким названием уже существует у этого предмета."
            )

        row = conn.execute(
            """
            SELECT tp.*,
                (
                    SELECT COUNT(*) FROM tasks t
                    WHERE t.subject_code = tp.subject_code
                      AND t.topic = tp.name
                      AND t.is_active = 1
                ) AS task_count
            FROM topics tp
            WHERE tp.id = ?
            """,
            (topic_id,)
        ).fetchone()

    return {
        "message": "Тема успешно обновлена.",
        "topic": topic_to_admin(row)
    }


@router.delete(
    "/topics/{topic_id}",
    dependencies=[Depends(require_admin)]
)
def deactivate_topic(topic_id: int):
    with get_connection() as conn:
        cursor = conn.execute(
            "UPDATE topics SET is_active = 0 WHERE id = ?",
            (topic_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Тема не найдена."
            )

    return {
        "message": "Тема отключена.",
        "topic_id": topic_id
    }


# =========================================================
# ADMIN ANALYTICS
# =========================================================

COMPLETED_STATUSES = ("checked", "reviewed")


def get_analytics_time():
    return datetime.now(timezone.utc).isoformat()


@router.get("/analytics/overview", dependencies=[Depends(require_admin)])
def get_analytics_overview():
    """Общая статистика платформы для администратора."""

    now = get_analytics_time()

    with get_connection() as conn:
        users = conn.execute("""
            SELECT
                COUNT(*) AS total_users,
                SUM(CASE WHEN role = 'student' THEN 1 ELSE 0 END)
                    AS total_students,
                SUM(CASE WHEN role = 'admin' THEN 1 ELSE 0 END)
                    AS total_admins
            FROM auth_users
        """).fetchone()

        active = conn.execute("""
            SELECT COUNT(DISTINCT u.id) AS active_students
            FROM auth_users u
            JOIN auth_sessions s ON s.user_id = u.id
            WHERE u.role = 'student'
              AND s.expires_at > ?
        """, (now,)).fetchone()

        attempts = conn.execute("""
            SELECT
                COUNT(*) AS total_attempts,
                SUM(CASE WHEN is_correct = 1 THEN 1 ELSE 0 END)
                    AS correct_attempts,
                SUM(CASE WHEN is_correct = 0 THEN 1 ELSE 0 END)
                    AS wrong_attempts,
                COUNT(DISTINCT user_id) AS students_with_attempts,
                COUNT(DISTINCT task_id) AS unique_tasks_solved
            FROM task_attempts
            WHERE status IN ('checked', 'reviewed')
              AND is_correct IS NOT NULL
        """).fetchone()

        pending = conn.execute("""
            SELECT COUNT(*) AS pending_reviews
            FROM task_attempts
            WHERE status = 'pending_review'
        """).fetchone()

        available_tasks = conn.execute("""
            SELECT COUNT(*) AS total
            FROM tasks
            WHERE is_active = 1
        """).fetchone()

        total_attempts = attempts["total_attempts"] or 0
        correct_attempts = attempts["correct_attempts"] or 0

        accuracy = (
            round(correct_attempts / total_attempts * 100, 2)
            if total_attempts else 0
        )

    return {
        "users": {
            "total": users["total_users"] or 0,
            "students": users["total_students"] or 0,
            "admins": users["total_admins"] or 0,
            "active_students": active["active_students"] or 0
        },
        "learning": {
            "total_attempts": total_attempts,
            "correct_attempts": correct_attempts,
            "wrong_attempts": attempts["wrong_attempts"] or 0,
            "accuracy_percent": accuracy,
            "students_with_attempts": attempts["students_with_attempts"] or 0,
            "unique_tasks_solved": attempts["unique_tasks_solved"] or 0,
            "available_tasks": available_tasks["total"] or 0
        },
        "reviews": {
            "pending": pending["pending_reviews"] or 0
        }
    }


@router.get("/analytics/students", dependencies=[Depends(require_admin)])
def get_students_analytics(
    limit: int = 50,
    offset: int = 0
):
    """Рейтинг учеников по результатам завершённых попыток."""

    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=400,
            detail="limit должен быть от 1 до 200."
        )

    if offset < 0:
        raise HTTPException(
            status_code=400,
            detail="offset не может быть отрицательным."
        )

    now = get_analytics_time()

    with get_connection() as conn:
        total = conn.execute("""
            SELECT COUNT(*) AS total
            FROM auth_users
            WHERE role = 'student'
        """).fetchone()["total"]

        rows = conn.execute("""
            WITH attempt_stats AS (
                SELECT
                    user_id,

                    COUNT(
                        CASE
                            WHEN status IN ('checked', 'reviewed')
                             AND is_correct IS NOT NULL
                            THEN 1
                        END
                    ) AS total_attempts,

                    SUM(
                        CASE
                            WHEN status IN ('checked', 'reviewed')
                             AND is_correct = 1
                            THEN 1 ELSE 0
                        END
                    ) AS correct_attempts,

                    SUM(
                        CASE
                            WHEN status IN ('checked', 'reviewed')
                             AND is_correct = 0
                            THEN 1 ELSE 0
                        END
                    ) AS wrong_attempts,

                    COUNT(DISTINCT CASE
                        WHEN status IN ('checked', 'reviewed')
                         AND is_correct IS NOT NULL
                        THEN task_id
                    END) AS unique_tasks_solved,

                    SUM(
                        CASE
                            WHEN status IN ('checked', 'reviewed')
                             AND is_correct IS NOT NULL
                            THEN COALESCE(score, 0)
                            ELSE 0
                        END
                    ) AS total_score,

                    SUM(
                        CASE
                            WHEN status IN ('checked', 'reviewed')
                             AND is_correct IS NOT NULL
                            THEN COALESCE(max_score, 0)
                            ELSE 0
                        END
                    ) AS max_score,

                    SUM(
                        CASE
                            WHEN status = 'pending_review'
                            THEN 1 ELSE 0
                        END
                    ) AS pending_reviews,

                    MAX(created_at) AS last_attempt_at

                FROM task_attempts
                GROUP BY user_id
            )

            SELECT
                u.id AS user_id,
                u.username,
                u.created_at,

                COALESCE(a.total_attempts, 0) AS total_attempts,
                COALESCE(a.correct_attempts, 0) AS correct_attempts,
                COALESCE(a.wrong_attempts, 0) AS wrong_attempts,
                COALESCE(a.unique_tasks_solved, 0) AS unique_tasks_solved,

                COALESCE(a.total_score, 0) AS total_score,
                COALESCE(a.max_score, 0) AS max_score,

                COALESCE(a.pending_reviews, 0) AS pending_reviews,
                a.last_attempt_at,

                CASE WHEN EXISTS (
                    SELECT 1
                    FROM auth_sessions s
                    WHERE s.user_id = u.id
                      AND s.expires_at > ?
                ) THEN 1 ELSE 0 END AS is_active

            FROM auth_users u

            LEFT JOIN attempt_stats a
                ON a.user_id = u.id

            WHERE u.role = 'student'

            ORDER BY
                CASE
                    WHEN COALESCE(a.total_attempts, 0) = 0
                    THEN 1 ELSE 0
                END ASC,

                (
                    CAST(COALESCE(a.correct_attempts, 0) AS REAL)
                    / NULLIF(COALESCE(a.total_attempts, 0), 0)
                ) DESC,

                COALESCE(a.unique_tasks_solved, 0) DESC,
                COALESCE(a.total_attempts, 0) DESC,

                (
                    CAST(COALESCE(a.total_score, 0) AS REAL)
                    / NULLIF(COALESCE(a.max_score, 0), 0)
                ) DESC,

                u.created_at DESC,
                u.id ASC

            LIMIT ? OFFSET ?
        """, (now, limit, offset)).fetchall()

    students = []

    for index, row in enumerate(rows):
        total_completed = row["total_attempts"] or 0
        correct = row["correct_attempts"] or 0
        wrong = row["wrong_attempts"] or 0

        total_score = row["total_score"] or 0
        max_score = row["max_score"] or 0

        accuracy = (
            round(correct / total_completed * 100, 2)
            if total_completed else 0
        )

        score_percent = (
            round(total_score / max_score * 100, 2)
            if max_score > 0 else 0
        )

        students.append({
            "rank": offset + index + 1,
            "user_id": row["user_id"],
            "username": row["username"],
            "created_at": row["created_at"],
            "is_active": bool(row["is_active"]),

            "total_attempts": total_completed,
            "correct_attempts": correct,
            "wrong_attempts": wrong,

            "unique_tasks_solved": row["unique_tasks_solved"] or 0,
            "accuracy_percent": accuracy,

            "total_score": round(total_score, 2),
            "max_score": round(max_score, 2),
            "score_percent": score_percent,

            "pending_reviews": row["pending_reviews"] or 0,
            "last_attempt_at": row["last_attempt_at"]
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "students": students
    }


@router.get(
    "/analytics/problem-topics",
    dependencies=[Depends(require_admin)]
)
def get_problem_topics_analytics(
    limit: int = 20
):
    """Темы, в которых ученики чаще всего допускают ошибки."""

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=400,
            detail="limit должен быть от 1 до 100."
        )

    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                t.subject_code,
                t.topic,

                COUNT(a.id) AS total_attempts,

                SUM(CASE
                    WHEN a.is_correct = 1 THEN 1
                    ELSE 0
                END) AS correct_attempts,

                SUM(CASE
                    WHEN a.is_correct = 0 THEN 1
                    ELSE 0
                END) AS wrong_attempts,

                COUNT(DISTINCT a.user_id) AS students_count,

                COUNT(DISTINCT CASE
                    WHEN a.is_correct = 0 THEN a.user_id
                END) AS students_with_errors

            FROM task_attempts a

            JOIN tasks t ON t.id = a.task_id

            WHERE a.status IN ('checked', 'reviewed')
              AND a.is_correct IS NOT NULL

            GROUP BY t.subject_code, t.topic

            HAVING COUNT(a.id) > 0

            ORDER BY
                (
                    CAST(
                        SUM(CASE WHEN a.is_correct = 0 THEN 1 ELSE 0 END)
                        AS REAL
                    ) / COUNT(a.id)
                ) DESC,
                wrong_attempts DESC

            LIMIT ?
        """, (limit,)).fetchall()

    topics = []

    for row in rows:
        total = row["total_attempts"] or 0
        wrong = row["wrong_attempts"] or 0
        correct = row["correct_attempts"] or 0

        topics.append({
            "subject_code": row["subject_code"],
            "topic": row["topic"],
            "total_attempts": total,
            "correct_attempts": correct,
            "wrong_attempts": wrong,
            "error_percent": round(wrong / total * 100, 2) if total else 0,
            "accuracy_percent": round(correct / total * 100, 2) if total else 0,
            "students_count": row["students_count"] or 0,
            "students_with_errors": row["students_with_errors"] or 0
        })

    return {
        "total": len(topics),
        "topics": topics
    }
