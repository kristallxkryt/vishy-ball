
"""
profile_routes.py
Личный кабинет, статистика и история подготовки к ЕГЭ.
Проект: «Высший балл»
"""

import sqlite3

from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from auth_routes import get_current_user


DB_PATH = Path(__file__).resolve().parent / "users.db"

router = APIRouter(
    prefix="/api/profile",
    tags=["Личный кабинет"]
)


# =====================================
# БАЗА ДАННЫХ
# =====================================

@contextmanager
def get_connection():
    """Открывает соединение с гарантированным закрытием."""
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_profile_tables():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_progress (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject_code TEXT NOT NULL,
                topic TEXT NOT NULL,
                total_answered INTEGER NOT NULL DEFAULT 0,
                correct_answers INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                total_score REAL NOT NULL DEFAULT 0,
                max_score REAL NOT NULL DEFAULT 0,
                UNIQUE(user_id, subject_code, topic)
            )
        """)

        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(user_progress)"
            ).fetchall()
        }

        if "total_score" not in columns:
            conn.execute("""
                ALTER TABLE user_progress
                ADD COLUMN total_score REAL NOT NULL DEFAULT 0
            """)

        if "max_score" not in columns:
            conn.execute("""
                ALTER TABLE user_progress
                ADD COLUMN max_score REAL NOT NULL DEFAULT 0
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_progress_user
            ON user_progress(user_id)
        """)


# =====================================
# МОДЕЛЬ РЕЗУЛЬТАТА
# =====================================

class AnswerRequest(BaseModel):
    subject_code: str = Field(min_length=2, max_length=30)
    topic: str = Field(min_length=2, max_length=100)
    is_correct: bool


# =====================================
# ЛИЧНЫЙ КАБИНЕТ
# =====================================

@router.get("/me")
def get_profile(
    current_user=Depends(get_current_user)
):
    return {
        "id": current_user["id"],
        "username": current_user["username"],
        "email": current_user["email"],
        "message": "Добро пожаловать в Высший балл!"
    }


# =====================================
# СОХРАНЕНИЕ РЕЗУЛЬТАТА
# =====================================

@router.post("/answer")
def save_answer(
    data: AnswerRequest,
    current_user=Depends(get_current_user)
):
    """
    Устаревший endpoint.

    Прогресс теперь начисляется исключительно через
    checking_routes.py после создания task_attempts.

    Endpoint оставлен для совместимости со старыми
    клиентами, но больше не изменяет статистику.
    """

    return {
        "message": (
            "Этот способ сохранения результата устарел. "
            "Используйте /api/checking/answer."
        ),
        "is_correct": data.is_correct,
        "progress_updated": False,
        "recommended_endpoint": "/api/checking/answer"
    }


# =====================================
# СТАТИСТИКА ПО ТЕМАМ
# =====================================

@router.get("/progress")
def get_progress(
    current_user=Depends(get_current_user)
):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                subject_code,
                topic,
                total_answered,
                correct_answers,
                updated_at,
                total_score,
                max_score
            FROM user_progress
            WHERE user_id = ?
            ORDER BY subject_code, topic
        """, (current_user["id"],)).fetchall()

    result = []

    for row in rows:
        total = row["total_answered"]
        correct = row["correct_answers"]

        accuracy = round(correct / total * 100, 1) if total else 0

        result.append({
            "subject_code": row["subject_code"],
            "topic": row["topic"],
            "total_answered": total,
            "correct_answers": correct,
            "wrong_answers": total - correct,
            "accuracy_percent": accuracy,
            "total_score": row["total_score"],
            "max_score": row["max_score"],
            "score_percent": (
                round(row["total_score"] / row["max_score"] * 100, 1)
                if row["max_score"] else 0
            ),
            "updated_at": row["updated_at"]
        })

    return {
        "progress": result
    }


# =====================================
# ОБЩАЯ СТАТИСТИКА ПО ПРЕДМЕТАМ
# =====================================

@router.get("/stats")
def get_statistics(
    current_user=Depends(get_current_user)
):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                subject_code,
                SUM(total_answered) AS total_answered,
                SUM(correct_answers) AS correct_answers,
                SUM(total_score) AS total_score,
                SUM(max_score) AS max_score
            FROM user_progress
            WHERE user_id = ?
            GROUP BY subject_code
            ORDER BY subject_code
        """, (current_user["id"],)).fetchall()

    subjects = []
    all_answered = 0
    all_correct = 0
    all_score = 0
    all_max_score = 0

    for row in rows:
        total = row["total_answered"]
        correct = row["correct_answers"]
        wrong = total - correct

        accuracy = (
            round(correct / total * 100, 1)
            if total else 0
        )

        total_score = row["total_score"] or 0
        max_score = row["max_score"] or 0

        subjects.append({
            "subject_code": row["subject_code"],
            "total_answered": total,
            "correct_answers": correct,
            "wrong_answers": wrong,
            "accuracy_percent": accuracy,
            "total_score": total_score,
            "max_score": max_score,
            "score_percent": (
                round(total_score / max_score * 100, 1)
                if max_score else 0
            )
        })

        all_answered += total
        all_correct += correct
        all_score += total_score
        all_max_score += max_score

    overall_accuracy = (
        round(all_correct / all_answered * 100, 1)
        if all_answered else 0
    )

    return {
        "total_answered": all_answered,
        "correct_answers": all_correct,
        "wrong_answers": all_answered - all_correct,
        "accuracy_percent": overall_accuracy,
        "total_score": all_score,
        "max_score": all_max_score,
        "score_percent": (
            round(all_score / all_max_score * 100, 1)
            if all_max_score else 0
        ),
        "subjects": subjects
    }


# =====================================
# РАСШИРЕННАЯ СТАТИСТИКА ПО ТЕМАМ
# =====================================

@router.get("/topic-stats")
def get_topic_statistics(
    subject_code: str | None = Query(
        default=None,
        min_length=2,
        max_length=30
    ),
    current_user=Depends(get_current_user)
):
    """
    Показывает статистику по всем активным темам,
    включая темы, которые ученик ещё не решал.
    """

    query = """
        SELECT
            t.subject_code,
            t.topic,
            COUNT(DISTINCT t.id) AS available_tasks,
            COALESCE(p.total_answered, 0) AS total_answered,
            COALESCE(p.correct_answers, 0) AS correct_answers,
            COALESCE(p.total_score, 0) AS total_score,
            COALESCE(p.max_score, 0) AS max_score
        FROM tasks t
        LEFT JOIN user_progress p
            ON p.user_id = ?
            AND p.subject_code = t.subject_code
            AND p.topic = t.topic
        WHERE t.is_active = 1
    """

    params = [current_user["id"]]

    if subject_code:
        query += " AND t.subject_code = ?"
        params.append(subject_code.strip().lower())

    query += """
        GROUP BY
            t.subject_code,
            t.topic,
            p.total_answered,
            p.correct_answers,
            p.total_score,
            p.max_score
        ORDER BY t.subject_code, t.topic
    """

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    topics = []
    subjects = {}

    total_available = 0
    total_answered = 0
    total_correct = 0
    total_score = 0
    total_max_score = 0

    for row in rows:
        available = row["available_tasks"]
        answered = row["total_answered"]
        correct = row["correct_answers"]
        wrong = answered - correct
        score = row["total_score"]
        max_score = row["max_score"]

        accuracy = (
            round(correct / answered * 100, 1)
            if answered else 0
        )

        topic_data = {
            "subject_code": row["subject_code"],
            "topic": row["topic"],
            "available_tasks": available,
            "total_answered": answered,
            "correct_answers": correct,
            "wrong_answers": wrong,
            "accuracy_percent": accuracy,
            "total_score": score,
            "max_score": max_score,
            "score_percent": (
                round(score / max_score * 100, 1)
                if max_score else 0
            ),
            "started": answered > 0
        }

        topics.append(topic_data)

        code = row["subject_code"]

        if code not in subjects:
            subjects[code] = {
                "subject_code": code,
                "total_topics": 0,
                "available_tasks": 0,
                "total_answered": 0,
                "correct_answers": 0,
                "wrong_answers": 0,
                "total_score": 0,
                "max_score": 0
            }

        subjects[code]["total_topics"] += 1
        subjects[code]["available_tasks"] += available
        subjects[code]["total_answered"] += answered
        subjects[code]["correct_answers"] += correct
        subjects[code]["wrong_answers"] += wrong
        subjects[code]["total_score"] += score
        subjects[code]["max_score"] += max_score

        total_available += available
        total_answered += answered
        total_correct += correct
        total_score += score
        total_max_score += max_score

    for subject in subjects.values():
        answered = subject["total_answered"]
        correct = subject["correct_answers"]

        subject["accuracy_percent"] = (
            round(correct / answered * 100, 1)
            if answered else 0
        )

        subject["score_percent"] = (
            round(
                subject["total_score"] / subject["max_score"] * 100,
                1
            )
            if subject["max_score"] else 0
        )

    return {
        "total_topics": len(topics),
        "total_available_tasks": total_available,
        "total_answered": total_answered,
        "correct_answers": total_correct,
        "wrong_answers": total_answered - total_correct,
        "accuracy_percent": (
            round(total_correct / total_answered * 100, 1)
            if total_answered else 0
        ),
        "total_score": total_score,
        "max_score": total_max_score,
        "score_percent": (
            round(total_score / total_max_score * 100, 1)
            if total_max_score else 0
        ),
        "subjects": list(subjects.values()),
        "topics": topics
    }


# =====================================
# ИСТОРИЯ РЕШЕНИЙ
# =====================================

@router.get("/history")
def get_history(
    subject_code: str | None = Query(
        default=None,
        min_length=2,
        max_length=30
    ),
    topic: str | None = Query(
        default=None,
        min_length=2,
        max_length=100
    ),
    status: str | None = Query(
        default=None,
        min_length=2,
        max_length=30
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user)
):
    conditions = ["a.user_id = ?"]
    parameters = [current_user["id"]]

    if subject_code:
        conditions.append("t.subject_code = ?")
        parameters.append(subject_code.strip().lower())

    if topic:
        conditions.append("t.topic = ?")
        parameters.append(topic.strip())

    if status:
        conditions.append("a.status = ?")
        parameters.append(status.strip().lower())

    where_sql = " AND ".join(conditions)

    with get_connection() as conn:
        total = conn.execute(f"""
            SELECT COUNT(*)
            FROM task_attempts a
            LEFT JOIN tasks t ON t.id = a.task_id
            WHERE {where_sql}
        """, parameters).fetchone()[0]

        rows = conn.execute(f"""
            SELECT
                a.id,
                a.task_id,
                t.subject_code,
                t.topic,
                t.question,
                t.task_type,
                a.submitted_answer,
                a.is_correct,
                a.status,
                a.score,
                a.max_score,
                a.review_comment,
                a.reviewed_at,
                a.reviewed_by,
                a.attempt_number,
                a.created_at
            FROM task_attempts a
            LEFT JOIN tasks t ON t.id = a.task_id
            WHERE {where_sql}
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT ? OFFSET ?
        """, parameters + [limit, offset]).fetchall()

    items = []

    for row in rows:
        items.append({
            "id": row["id"],
            "task_id": row["task_id"],
            "subject_code": row["subject_code"],
            "topic": row["topic"],
            "question": row["question"],
            "task_type": row["task_type"],
            "submitted_answer": row["submitted_answer"],
            "is_correct": (
                bool(row["is_correct"])
                if row["is_correct"] is not None
                else None
            ),
            "status": row["status"],
            "score": row["score"],
            "max_score": row["max_score"],
            "review_comment": row["review_comment"],
            "reviewed_at": row["reviewed_at"],
            "reviewed_by": row["reviewed_by"],
            "attempt_number": row["attempt_number"],
            "created_at": row["created_at"]
        })

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items
    }


# =====================================
# СОЗДАНИЕ ТАБЛИЦ
# =====================================

init_profile_tables()
