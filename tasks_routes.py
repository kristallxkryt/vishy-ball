
"""
tasks_routes.py
Каталог предметов, тем и банк заданий ЕГЭ.
Проект: «Высший балл»
"""

import json
import sqlite3

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel


router = APIRouter(
    prefix="/api/tasks",
    tags=["Задания ЕГЭ"]
)

DB_PATH = Path(__file__).resolve().parent / "users.db"


# --------------------------------------------------
# ПРЕДМЕТЫ ЕГЭ
# --------------------------------------------------

SUBJECTS = [
    ("russian", "Русский язык"),
    ("math-basic", "Математика (базовая)"),
    ("math-profile", "Математика (профильная)"),
    ("informatics", "Информатика"),
    ("physics", "Физика"),
    ("chemistry", "Химия"),
    ("biology", "Биология"),
    ("history", "История"),
    ("social-studies", "Обществознание"),
    ("literature", "Литература"),
    ("geography", "География"),
    ("english", "Английский язык"),
    ("german", "Немецкий язык"),
    ("french", "Французский язык"),
    ("spanish", "Испанский язык"),
    ("chinese", "Китайский язык"),
]


# --------------------------------------------------
# ПОДКЛЮЧЕНИЕ К БАЗЕ
# --------------------------------------------------

@contextmanager
def get_tasks_connection():
    """Создаёт подключение с гарантированным закрытием."""

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


# --------------------------------------------------
# СОЗДАНИЕ И ОБНОВЛЕНИЕ СТРУКТУРЫ БАЗЫ
# --------------------------------------------------

def init_tasks_db():
    """Создаёт таблицы каталога и заданий."""

    with get_tasks_connection() as conn:

        # Таблица предметов
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

        # Таблица тем
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

        # Таблица заданий.
        # Существующая структура сохраняется.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject_code TEXT NOT NULL,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                hint TEXT,
                explanation TEXT,
                difficulty TEXT DEFAULT 'medium',
                source TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        existing_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(tasks)"
            ).fetchall()
        }

        new_columns = {
            "task_type": "TEXT NOT NULL DEFAULT 'text'",
            "options_json": "TEXT NOT NULL DEFAULT '[]'",
            "media_json": "TEXT NOT NULL DEFAULT '[]'",
            "checking_config_json": "TEXT NOT NULL DEFAULT '{}'",
            "exam_number": "INTEGER",
            "variant_label": "TEXT",
        }

        for column_name, column_type in new_columns.items():
            if column_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE tasks ADD COLUMN "
                    f"{column_name} {column_type}"
                )

        # Индексы заданий
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_subject
            ON tasks(subject_code)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_topic
            ON tasks(topic)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_subject_topic_active
            ON tasks(subject_code, topic, is_active)
        """)

        # Индексы каталога
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topics_subject
            ON topics(subject_code, is_active)
        """)

        # Добавляем предметы, если их ещё нет.
        # Существующие записи не перезаписываются.
        conn.executemany("""
            INSERT OR IGNORE INTO subjects (
                subject_code,
                name,
                sort_order
            )
            VALUES (?, ?, ?)
        """, [
            (code, name, index)
            for index, (code, name) in enumerate(SUBJECTS, start=1)
        ])


init_tasks_db()


# --------------------------------------------------
# МОДЕЛИ
# --------------------------------------------------


class TaskPublic(BaseModel):
    id: int
    subject_code: str
    topic: str
    question: str
    difficulty: str | None = None
    task_type: str = "text"
    options: Any = []
    media: list[dict] = []
    exam_number: int | None = None
    variant_label: str | None = None


# --------------------------------------------------
# БЕЗОПАСНОЕ ПРЕДСТАВЛЕНИЕ ЗАДАНИЯ
# --------------------------------------------------


def task_to_public(row):
    """Возвращает безопасные поля задания для ученика."""

    try:
        options = json.loads(row["options_json"] or "[]")
    except (ValueError, TypeError):
        options = []

    try:
        media = json.loads(row["media_json"] or "[]")
    except (ValueError, TypeError):
        media = []

    return {
        "id": row["id"],
        "subject_code": row["subject_code"],
        "topic": row["topic"],
        "question": row["question"],
        "difficulty": row["difficulty"],
        "task_type": row["task_type"],
        "exam_number": row["exam_number"] if "exam_number" in row.keys() else None,
        "variant_label": row["variant_label"] if "variant_label" in row.keys() else None,
        "options": options,
        "media": media,
    }



# --------------------------------------------------
# ПОЛУЧЕНИЕ СПИСКА ПРЕДМЕТОВ
# --------------------------------------------------

@router.get("/subjects")
def get_subjects():
    """Возвращает все активные предметы."""

    with get_tasks_connection() as conn:
        rows = conn.execute("""
            SELECT
                s.subject_code,
                s.name,
                s.sort_order,
                COUNT(DISTINCT t.id) AS task_count

            FROM subjects s

            LEFT JOIN tasks t
                ON t.subject_code = s.subject_code
                AND t.is_active = 1

            WHERE s.is_active = 1

            GROUP BY
                s.id,
                s.subject_code,
                s.name,
                s.sort_order

            ORDER BY s.sort_order, s.name
        """).fetchall()

    subjects = [
        {
            "subject_code": row["subject_code"],
            "name": row["name"],
            "task_count": row["task_count"]
        }
        for row in rows
    ]

    return {
        "total_subjects": len(subjects),
        "subjects": subjects
    }


# --------------------------------------------------
# КАТАЛОГ ТЕМ ОДНОГО ПРЕДМЕТА
# --------------------------------------------------

@router.get("/topics")
def get_topics(
    subject_code: str = Query(
        min_length=2,
        max_length=30
    )
):
    """
    Возвращает темы выбранного предмета.

    Показывает темы из отдельного каталога,
    а также старые темы, найденные в заданиях.
    """

    subject_code = subject_code.strip().lower()

    with get_tasks_connection() as conn:

        subject = conn.execute("""
            SELECT subject_code, name
            FROM subjects
            WHERE subject_code = ?
              AND is_active = 1
        """, (subject_code,)).fetchone()

        if subject is None:
            raise HTTPException(
                status_code=404,
                detail="Предмет не найден."
            )

        catalog_rows = conn.execute("""
            SELECT
                id,
                name,
                description,
                sort_order

            FROM topics

            WHERE subject_code = ?
              AND is_active = 1
        """, (subject_code,)).fetchall()

        task_rows = conn.execute("""
            SELECT
                topic,
                COUNT(*) AS task_count

            FROM tasks

            WHERE subject_code = ?
              AND is_active = 1

            GROUP BY topic
        """, (subject_code,)).fetchall()

    topics = {}

    for row in catalog_rows:
        topics[row["name"]] = {
            "topic_id": row["id"],
            "topic": row["name"],
            "description": row["description"],
            "task_count": 0,
            "sort_order": row["sort_order"]
        }

    for row in task_rows:
        name = row["topic"]

        if name not in topics:
            topics[name] = {
                "topic_id": None,
                "topic": name,
                "description": None,
                "task_count": row["task_count"],
                "sort_order": 999999
            }
        else:
            topics[name]["task_count"] = row["task_count"]

    result = sorted(
        topics.values(),
        key=lambda item: (
            item["sort_order"],
            item["topic"]
        )
    )

    for item in result:
        item.pop("sort_order")

    return {
        "subject_code": subject_code,
        "subject_name": subject["name"],
        "total_topics": len(result),
        "total_tasks": sum(
            item["task_count"] for item in result
        ),
        "topics": result
    }


# --------------------------------------------------
# ПОЛНЫЙ КАТАЛОГ ПРЕДМЕТОВ И ТЕМ
# --------------------------------------------------

@router.get("/catalog")
def get_tasks_catalog():
    """
    Возвращает все предметы, включая предметы
    без заданий, и все зарегистрированные темы.
    """

    with get_tasks_connection() as conn:

        subject_rows = conn.execute("""
            SELECT
                subject_code,
                name,
                sort_order

            FROM subjects

            WHERE is_active = 1

            ORDER BY sort_order, name
        """).fetchall()

        topic_rows = conn.execute("""
            SELECT
                id,
                subject_code,
                name,
                description,
                sort_order

            FROM topics

            WHERE is_active = 1

            ORDER BY sort_order, name
        """).fetchall()

        task_rows = conn.execute("""
            SELECT
                subject_code,
                topic,
                COUNT(*) AS task_count

            FROM tasks

            WHERE is_active = 1

            GROUP BY subject_code, topic
        """).fetchall()

    subjects = {}

    for row in subject_rows:
        subjects[row["subject_code"]] = {
            "subject_code": row["subject_code"],
            "name": row["name"],
            "total_tasks": 0,
            "topics": {}
        }

    # Добавляем темы из отдельного каталога
    for row in topic_rows:
        code = row["subject_code"]

        if code not in subjects:
            continue

        subjects[code]["topics"][row["name"]] = {
            "topic_id": row["id"],
            "topic": row["name"],
            "description": row["description"],
            "task_count": 0,
            "sort_order": row["sort_order"]
        }

    # Добавляем количество заданий.
    # Поддерживаем также старые темы,
    # которые ещё не внесены в таблицу topics.
    for row in task_rows:
        code = row["subject_code"]
        name = row["topic"]
        count = row["task_count"]

        if code not in subjects:
            continue

        subject = subjects[code]

        if name not in subject["topics"]:
            subject["topics"][name] = {
                "topic_id": None,
                "topic": name,
                "description": None,
                "task_count": count,
                "sort_order": 999999
            }
        else:
            subject["topics"][name]["task_count"] = count

        subject["total_tasks"] += count

    result = []

    for subject in subjects.values():

        topics = sorted(
            subject["topics"].values(),
            key=lambda item: (
                item["sort_order"],
                item["topic"]
            )
        )

        for topic in topics:
            topic.pop("sort_order")

        result.append({
            "subject_code": subject["subject_code"],
            "name": subject["name"],
            "total_topics": len(topics),
            "total_tasks": subject["total_tasks"],
            "topics": topics
        })

    return {
        "total_subjects": len(result),
        "total_topics": sum(
            subject["total_topics"]
            for subject in result
        ),
        "total_tasks": sum(
            subject["total_tasks"]
            for subject in result
        ),
        "subjects": result
    }


# --------------------------------------------------
# ПОЛУЧЕНИЕ СПИСКА ЗАДАНИЙ
# --------------------------------------------------

@router.get("/", response_model=list[TaskPublic])
def get_tasks(
    subject_code: str | None = None,
    topic: str | None = None,
    difficulty: str | None = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0)
):
    """Получает список активных заданий с фильтрацией."""

    query = """
        SELECT
            id,
            subject_code,
            topic,
            question,
            difficulty,
            task_type,
            options_json,
            media_json,
            exam_number,
            variant_label

        FROM tasks

        WHERE is_active = 1
    """

    params = []

    if subject_code:
        query += " AND subject_code = ?"
        params.append(subject_code.strip().lower())

    if topic:
        query += " AND topic LIKE ?"
        params.append(f"%{topic}%")

    if difficulty:
        query += " AND difficulty = ?"
        params.append(difficulty)

    query += " ORDER BY id LIMIT ? OFFSET ?"

    params.extend([limit, offset])

    with get_tasks_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    return [
        task_to_public(row)
        for row in rows
    ]


# --------------------------------------------------
# ПОЛУЧЕНИЕ ОДНОГО ЗАДАНИЯ
# --------------------------------------------------

@router.get("/{task_id}", response_model=TaskPublic)
def get_task(task_id: int):
    """Получает одно активное задание по ID."""

    with get_tasks_connection() as conn:
        row = conn.execute("""
            SELECT * FROM tasks

            WHERE id = ?
              AND is_active = 1
        """, (task_id,)).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Задание не найдено."
        )

    return task_to_public(row)
