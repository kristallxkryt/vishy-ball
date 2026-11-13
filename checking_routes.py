
"""
checking_routes.py

Проверка ответов, начисление баллов и ручная проверка.
Поддерживает самостоятельную практику и назначенные варианты.

Проект: «Высший балл»

Самостоятельная практика:
- ученик может решать задания повторно;
- каждая попытка сохраняется отдельно;
- результаты учитываются в личной статистике.

Назначенные варианты:
- ответы берутся из assignment_answers;
- проверка выполняется при завершении варианта;
- task_attempts связывается с assignment_attempt_id;
- одно задание в одной попытке проверяется только один раз;
- ручная проверка доступна администратору и учителю,
  которому принадлежит назначение;
- самостоятельная практика не отображается учителю.
"""

import json
import math
import sqlite3

from pathlib import Path
from datetime import datetime, timezone
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_routes import get_current_user, require_admin


router = APIRouter(
    prefix="/api/checking",
    tags=["Проверка ответов"]
)

DB_PATH = Path(__file__).resolve().parent / "users.db"


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_columns(conn, table_name: str) -> dict:
    return {
        row["name"]: row
        for row in conn.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


def init_checking_db():
    """Создаёт таблицы и безопасно расширяет существующую БД."""

    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                submitted_answer TEXT NOT NULL,
                is_correct INTEGER,
                attempt_number INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'checked',
                score REAL,
                max_score REAL,
                review_comment TEXT,
                reviewed_at TEXT,
                reviewed_by TEXT
            )
        """)

        columns = table_columns(conn, "task_attempts")

        # Совместимость со старой схемой, где is_correct
        # был обязательным полем.

        if (
            "is_correct" in columns
            and columns["is_correct"]["notnull"] == 1
        ):
            conn.execute("""
                CREATE TABLE task_attempts_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    task_id INTEGER NOT NULL,
                    submitted_answer TEXT NOT NULL,
                    is_correct INTEGER,
                    attempt_number INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL DEFAULT 'checked',
                    score REAL,
                    max_score REAL,
                    review_comment TEXT,
                    reviewed_at TEXT,
                    reviewed_by TEXT
                )
            """)

            old_columns = table_columns(
                conn,
                "task_attempts"
            )

            extra_fields = [
                "status",
                "score",
                "max_score",
                "review_comment",
                "reviewed_at",
                "reviewed_by"
            ]

            select_extras = [
                field if field in old_columns
                else ("'checked'" if field == "status" else "NULL")
                for field in extra_fields
            ]

            conn.execute(f"""
                INSERT INTO task_attempts_new (
                    id,
                    user_id,
                    task_id,
                    submitted_answer,
                    is_correct,
                    attempt_number,
                    created_at,
                    status,
                    score,
                    max_score,
                    review_comment,
                    reviewed_at,
                    reviewed_by
                )
                SELECT
                    id,
                    user_id,
                    task_id,
                    submitted_answer,
                    is_correct,
                    attempt_number,
                    created_at,
                    {", ".join(select_extras)}
                FROM task_attempts
            """)

            conn.execute("DROP TABLE task_attempts")

            conn.execute("""
                ALTER TABLE task_attempts_new
                RENAME TO task_attempts
            """)

        columns = table_columns(
            conn,
            "task_attempts"
        )

        migrations = {
            "status": "TEXT NOT NULL DEFAULT 'checked'",
            "score": "REAL",
            "max_score": "REAL",
            "review_comment": "TEXT",
            "reviewed_at": "TEXT",
            "reviewed_by": "TEXT",
            "assignment_attempt_id": (
                "INTEGER REFERENCES assignment_attempts(id) "
                "ON DELETE CASCADE"
            )
        }

        for name, definition in migrations.items():
            if name not in columns:
                conn.execute(
                    f"""
                    ALTER TABLE task_attempts
                    ADD COLUMN {name} {definition}
                    """
                )

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attempts_user_task
            ON task_attempts(user_id, task_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attempts_status
            ON task_attempts(status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_attempts_assignment
            ON task_attempts(assignment_attempt_id)
        """)

        # Одно задание может быть проверено только один раз
        # внутри одной попытки назначенного варианта.

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_assignment_attempt_task_unique
            ON task_attempts(assignment_attempt_id, task_id)
            WHERE assignment_attempt_id IS NOT NULL
        """)

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

        progress_columns = table_columns(
            conn,
            "user_progress"
        )

        if "total_score" not in progress_columns:
            conn.execute("""
                ALTER TABLE user_progress
                ADD COLUMN total_score REAL NOT NULL DEFAULT 0
            """)

        if "max_score" not in progress_columns:
            conn.execute("""
                ALTER TABLE user_progress
                ADD COLUMN max_score REAL NOT NULL DEFAULT 0
            """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_progress_user
            ON user_progress(user_id)
        """)


init_checking_db()


# =========================================================
# MODELS
# =========================================================

class AnswerRequest(BaseModel):
    task_id: int = Field(gt=0)
    answer: Any


class ReviewRequest(BaseModel):
    criterion_scores: dict[str, float] | None = None
    score: float | None = Field(default=None, ge=0)
    comment: str | None = Field(default=None, max_length=10000)


# =========================================================
# HELPERS
# =========================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_answer(answer: str) -> str:
    return " ".join(answer.strip().casefold().split())


def validate_number(value: Any, field_name: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Некорректное числовое значение: {field_name}."
        )

    return float(value)


def parse_json(raw: str | None, fallback: Any):
    if not raw:
        return fallback

    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="В базе обнаружен некорректный JSON."
        )


def serialize_answer(answer: Any) -> str:
    try:
        result = json.dumps(
            answer,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False
        )
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="Некорректный формат ответа."
        )

    if len(result) > 20000:
        raise HTTPException(
            status_code=422,
            detail="Ответ слишком большой."
        )

    return result


def decode_assignment_answer(raw: str) -> Any:
    """
    assignment_answers.answer хранит текст.
    Если в нём JSON, восстанавливаем исходный тип ответа.
    Если это обычный текст, возвращаем строку.
    """

    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


def parse_checking_config(task) -> dict:
    config = parse_json(
        task["checking_config_json"],
        {}
    )

    if not isinstance(config, dict):
        raise HTTPException(
            status_code=500,
            detail="Настройки проверки должны быть JSON-объектом."
        )

    return config


def get_grading_config(config: dict) -> dict:
    grading = config.get("grading", {})

    if not isinstance(grading, dict):
        raise HTTPException(
            status_code=500,
            detail="Некорректная конфигурация grading."
        )

    criteria = grading.get("criteria", [])

    if not isinstance(criteria, list):
        raise HTTPException(
            status_code=500,
            detail="Критерии оценивания должны быть массивом."
        )

    if "max_score" not in grading and criteria:
        max_score = 0.0

        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise HTTPException(
                    status_code=500,
                    detail="Некорректный критерий оценивания."
                )

            value = validate_number(
                criterion.get("max_score"),
                "max_score критерия"
            )

            if value < 0:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Максимальный балл критерия "
                        "не может быть отрицательным."
                    )
                )

            max_score += value
    else:
        max_score = validate_number(
            grading.get("max_score", 1),
            "grading.max_score"
        )

    if max_score <= 0:
        raise HTTPException(
            status_code=500,
            detail="max_score должен быть положительным числом."
        )

    mode = grading.get("mode", "exact")

    if mode not in ("exact", "rules", "manual"):
        raise HTTPException(
            status_code=500,
            detail="Неизвестный режим проверки задания."
        )

    return {
        **grading,
        "max_score": float(max_score),
        "mode": mode
    }


def is_fully_correct(score: float, max_score: float) -> bool:
    return math.isclose(
        score,
        max_score,
        rel_tol=0,
        abs_tol=0.000001
    )


def require_teacher(user: dict):
    if user["role"] != "teacher":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только учителям."
        )

    return user


def get_task_for_checking(conn, task_id: int):
    task = conn.execute("""
        SELECT
            id,
            subject_code,
            topic,
            answer,
            hint,
            explanation,
            task_type,
            checking_config_json
        FROM tasks
        WHERE id = ?
          AND is_active = 1
    """, (task_id,)).fetchone()

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Задание не найдено или неактивно."
        )

    return task


# =========================================================
# EXACT ANSWER CHECKING
# =========================================================

def check_structured_answer(
    task_type: str,
    submitted: Any,
    config: dict,
    task_answer: str | None = None
) -> bool:

    if task_type == "text":
        if not isinstance(submitted, str):
            raise HTTPException(
                status_code=422,
                detail="Для этого задания необходимо отправить текст."
            )

        expected = config.get(
            "correct_answer",
            task_answer
        )

        if expected is None:
            raise HTTPException(
                status_code=500,
                detail="Не настроен правильный ответ."
            )

        return (
            normalize_answer(submitted)
            == normalize_answer(str(expected))
        )

    if task_type == "single_choice":
        if not isinstance(submitted, str):
            raise HTTPException(
                status_code=422,
                detail="Выберите один вариант ответа."
            )

        expected = config.get("correct_option_id")

        if expected is None:
            raise HTTPException(
                status_code=500,
                detail="Не настроен правильный вариант ответа."
            )

        return submitted == str(expected)

    if task_type == "multiple_choice":
        if (
            not isinstance(submitted, list)
            or not all(isinstance(item, str) for item in submitted)
        ):
            raise HTTPException(
                status_code=422,
                detail="Отправьте массив ID выбранных вариантов."
            )

        if len(submitted) != len(set(submitted)):
            raise HTTPException(
                status_code=422,
                detail="В ответе обнаружены повторяющиеся варианты."
            )

        expected = config.get("correct_option_ids")

        if (
            not isinstance(expected, list)
            or not all(isinstance(item, str) for item in expected)
        ):
            raise HTTPException(
                status_code=500,
                detail="Некорректно настроены правильные варианты."
            )

        return set(submitted) == set(expected)

    if task_type == "matching":
        if (
            not isinstance(submitted, dict)
            or not all(
                isinstance(k, str) and isinstance(v, str)
                for k, v in submitted.items()
            )
        ):
            raise HTTPException(
                status_code=422,
                detail="Отправьте объект с парами соответствий."
            )

        expected = config.get("correct_pairs")

        if not isinstance(expected, dict):
            raise HTTPException(
                status_code=500,
                detail="Некорректно настроены пары соответствий."
            )

        return submitted == expected

    if task_type == "ordering":
        if (
            not isinstance(submitted, list)
            or not all(isinstance(item, str) for item in submitted)
        ):
            raise HTTPException(
                status_code=422,
                detail="Отправьте массив элементов в заданном порядке."
            )

        expected = config.get("correct_order")

        if not isinstance(expected, list):
            raise HTTPException(
                status_code=500,
                detail="Не настроена правильная последовательность."
            )

        return submitted == expected

    raise HTTPException(
        status_code=500,
        detail="Неизвестный тип задания."
    )


# =========================================================
# CONFIGURABLE PARTIAL SCORING
# =========================================================

def rule_matches(submitted: Any, condition: dict) -> bool:
    if not isinstance(condition, dict):
        return False

    rule_type = condition.get("type")
    expected = condition.get("value")

    if rule_type == "equals":
        return submitted == expected

    if rule_type == "contains_all":
        if isinstance(submitted, list) and isinstance(expected, list):
            return all(item in submitted for item in expected)

        if isinstance(submitted, dict) and isinstance(expected, dict):
            return all(
                submitted.get(key) == value
                for key, value in expected.items()
            )

        return False

    if rule_type == "contains_any":
        if isinstance(submitted, list) and isinstance(expected, list):
            return any(item in submitted for item in expected)

        return False

    if rule_type == "key_values":
        if not isinstance(submitted, dict) or not isinstance(expected, dict):
            return False

        return all(
            submitted.get(key) == value
            for key, value in expected.items()
        )

    if rule_type == "text_contains":
        if not isinstance(submitted, str) or not isinstance(expected, str):
            return False

        return (
            normalize_answer(expected)
            in normalize_answer(submitted)
        )

    return False


def calculate_rule_score(
    submitted: Any,
    grading: dict
) -> float:
    rules = grading.get("rules")

    if not isinstance(rules, list):
        raise HTTPException(
            status_code=500,
            detail="Для режима rules необходимо указать массив rules."
        )

    max_score = grading["max_score"]
    matching_scores = []

    for rule in rules:
        if not isinstance(rule, dict):
            continue

        condition = rule.get("condition")

        score = validate_number(
            rule.get("score"),
            "score правила"
        )

        if score < 0 or score > max_score:
            raise HTTPException(
                status_code=500,
                detail="Некорректный балл в правиле проверки."
            )

        if rule_matches(submitted, condition):
            matching_scores.append(score)

    return max(matching_scores, default=0.0)


# =========================================================
# CHECK ONE ANSWER
# =========================================================

def evaluate_answer(task, submitted: Any):
    """
    Возвращает результат проверки.
    Ручные задания не получают баллы до проверки человеком.
    """

    task_type = task["task_type"] or "text"
    config = parse_checking_config(task)
    grading = get_grading_config(config)
    max_score = grading["max_score"]

    if task_type == "long_text" or grading["mode"] == "manual":
        if not isinstance(submitted, str):
            raise HTTPException(
                status_code=422,
                detail="Развёрнутый ответ должен быть текстом."
            )

        if not submitted.strip():
            raise HTTPException(
                status_code=422,
                detail="Ответ не может быть пустым."
            )

        if len(submitted) > 10000:
            raise HTTPException(
                status_code=422,
                detail="Ответ слишком большой."
            )

        return {
            "status": "pending_review",
            "is_correct": None,
            "score": None,
            "max_score": max_score
        }

    if grading["mode"] == "rules":
        score = calculate_rule_score(
            submitted,
            grading
        )

    elif grading["mode"] == "exact":
        correct = check_structured_answer(
            task_type,
            submitted,
            config,
            task["answer"]
        )

        score = max_score if correct else 0.0

    else:
        raise HTTPException(
            status_code=500,
            detail="Неизвестный режим проверки задания."
        )

    correct = is_fully_correct(
        score,
        max_score
    )

    return {
        "status": "checked",
        "is_correct": int(correct),
        "score": score,
        "max_score": max_score
    }


# =========================================================
# PROGRESS
# =========================================================

def update_progress(
    conn,
    user_id: int,
    task,
    score: float,
    max_score: float,
    now: str
):
    if (
        not math.isfinite(score)
        or not math.isfinite(max_score)
        or max_score <= 0
        or score < 0
        or score > max_score
    ):
        raise HTTPException(
            status_code=500,
            detail="Некорректные значения баллов при обновлении прогресса."
        )

    subject_code = (task["subject_code"] or "").strip().lower()
    topic = (task["topic"] or "Без темы").strip()

    fully_correct = int(
        is_fully_correct(score, max_score)
    )

    conn.execute("""
        INSERT INTO user_progress (
            user_id,
            subject_code,
            topic,
            total_answered,
            correct_answers,
            updated_at,
            total_score,
            max_score
        )
        VALUES (?, ?, ?, 1, ?, ?, ?, ?)

        ON CONFLICT(user_id, subject_code, topic)
        DO UPDATE SET
            total_answered = total_answered + 1,
            correct_answers =
                correct_answers + excluded.correct_answers,
            total_score = total_score + excluded.total_score,
            max_score = max_score + excluded.max_score,
            updated_at = excluded.updated_at
    """, (
        user_id,
        subject_code,
        topic,
        fully_correct,
        now,
        score,
        max_score
    ))


# =========================================================
# ATTEMPT NUMBER
# =========================================================

def get_next_attempt_number(
    conn,
    user_id: int,
    task_id: int
) -> int:
    result = conn.execute("""
        SELECT COUNT(*) AS total
        FROM task_attempts
        WHERE user_id = ?
          AND task_id = ?
          AND assignment_attempt_id IS NULL
    """, (
        user_id,
        task_id
    )).fetchone()

    return result["total"] + 1


# =========================================================
# STANDALONE PRACTICE
# =========================================================

@router.post("/answer")
def check_answer(
    data: AnswerRequest,
    current_user=Depends(get_current_user)
):
    user_id = current_user["id"]
    now = now_iso()

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        task = get_task_for_checking(
            conn,
            data.task_id
        )

        result = evaluate_answer(
            task,
            data.answer
        )

        attempt_number = get_next_attempt_number(
            conn,
            user_id,
            data.task_id
        )

        submitted_answer = (
            data.answer
            if isinstance(data.answer, str)
            else serialize_answer(data.answer)
        )

        cursor = conn.execute("""
            INSERT INTO task_attempts (
                user_id,
                task_id,
                submitted_answer,
                is_correct,
                attempt_number,
                created_at,
                status,
                score,
                max_score,
                assignment_attempt_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """, (
            user_id,
            data.task_id,
            submitted_answer,
            result["is_correct"],
            attempt_number,
            now,
            result["status"],
            result["score"],
            result["max_score"]
        ))

        attempt_id = cursor.lastrowid

        if result["status"] == "checked":
            update_progress(
                conn,
                user_id,
                task,
                result["score"],
                result["max_score"],
                now
            )

    if result["status"] == "pending_review":
        return {
            "status": "pending_review",
            "attempt_id": attempt_id,
            "is_correct": None,
            "score": None,
            "max_score": result["max_score"],
            "attempt": attempt_number,
            "message": (
                "Ответ отправлен и ожидает проверки."
            )
        }

    correct = bool(result["is_correct"])

    response = {
        "status": "correct" if correct else "incorrect",
        "attempt_id": attempt_id,
        "is_correct": correct,
        "score": result["score"],
        "max_score": result["max_score"],
        "attempt": attempt_number
    }

    if correct:
        response["message"] = "Правильно! Отличная работа."

    elif attempt_number == 1:
        response["message"] = "Ответ неверный. Попробуй ещё раз."
        response["hint"] = (
            task["hint"]
            or "Попробуй внимательно разобрать условие."
        )

    else:
        response["message"] = "Ответ снова неверный. Изучи решение."
        response["explanation"] = (
            task["explanation"]
            or "Подробное объяснение для этого задания пока не добавлено."
        )

    return response


# =========================================================
# ASSIGNMENT HELPERS
# =========================================================

def get_assignment_attempt_for_checking(
    conn,
    assignment_attempt_id: int
):
    attempt = conn.execute("""
        SELECT
            aa.id,
            aa.assignment_id,
            aa.student_id,
            aa.status,
            a.variant_id,
            a.class_id,
            a.teacher_id,
            a.status AS assignment_status
        FROM assignment_attempts aa
        JOIN class_assignments a
            ON a.id = aa.assignment_id
        WHERE aa.id = ?
    """, (
        assignment_attempt_id
    )).fetchone()

    if attempt is None:
        raise HTTPException(
            status_code=404,
            detail="Попытка назначенной работы не найдена."
        )

    return attempt


def finalize_assignment_attempt(
    conn,
    assignment_attempt_id: int
):
    """
    Если все ручные ответы проверены, переводит
    попытку назначенной работы в reviewed.

    Автоматически проверенные ответы имеют статус checked.
    """

    pending = conn.execute("""
        SELECT COUNT(*) AS total
        FROM task_attempts
        WHERE assignment_attempt_id = ?
          AND status = 'pending_review'
    """, (
        assignment_attempt_id
    )).fetchone()["total"]

    if pending == 0:
        reviewed = conn.execute("""
            SELECT COUNT(*) AS total
            FROM task_attempts
            WHERE assignment_attempt_id = ?
              AND status = 'reviewed'
        """, (
            assignment_attempt_id
        )).fetchone()["total"]

        if reviewed > 0:
            conn.execute("""
                UPDATE assignment_attempts
                SET status = 'reviewed'
                WHERE id = ?
                  AND status = 'submitted'
            """, (
                assignment_attempt_id
            ))


def process_assignment_submission(
    conn,
    assignment_attempt_id: int
):
    """
    Проверяет сохранённые ответы назначенного варианта
    и создаёт связанные записи task_attempts.

    Выполняется внутри одной транзакции с завершением
    assignment_attempts.
    """

    attempt = get_assignment_attempt_for_checking(
        conn,
        assignment_attempt_id
    )

    if attempt["status"] != "in_progress":
        raise HTTPException(
            status_code=409,
            detail="Эта попытка уже была отправлена."
        )

    tasks = conn.execute("""
        SELECT
            vt.task_id,
            t.id,
            t.subject_code,
            t.topic,
            t.answer,
            t.hint,
            t.explanation,
            t.task_type,
            t.checking_config_json,
            ans.answer AS submitted_answer

        FROM variant_tasks vt

        JOIN tasks t
            ON t.id = vt.task_id

        LEFT JOIN assignment_answers ans
            ON ans.task_id = vt.task_id
           AND ans.attempt_id = ?

        WHERE vt.variant_id = ?

        ORDER BY vt.position
    """, (
        assignment_attempt_id,
        attempt["variant_id"]
    )).fetchall()

    if not tasks:
        raise HTTPException(
            status_code=400,
            detail="В назначенном варианте нет заданий."
        )

    missing = [
        row["task_id"]
        for row in tasks
        if row["submitted_answer"] is None
    ]

    if missing:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Не на все задания сохранены ответы.",
                "missing_task_ids": missing,
                "missing_count": len(missing)
            }
        )

    # Защита от повторного создания записей проверки.

    existing = conn.execute("""
        SELECT COUNT(*) AS total
        FROM task_attempts
        WHERE assignment_attempt_id = ?
    """, (
        assignment_attempt_id
    )).fetchone()["total"]

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Ответы этой попытки уже переданы на проверку."
        )

    now = now_iso()
    created_attempts = []

    for task in tasks:
        submitted = decode_assignment_answer(
            task["submitted_answer"]
        )

        result = evaluate_answer(
            task,
            submitted
        )

        attempt_number = get_next_attempt_number(
            conn,
            attempt["student_id"],
            task["task_id"]
        )

        stored_answer = (
            task["submitted_answer"]
            if isinstance(task["submitted_answer"], str)
            else serialize_answer(submitted)
        )

        cursor = conn.execute("""
            INSERT INTO task_attempts (
                user_id,
                task_id,
                submitted_answer,
                is_correct,
                attempt_number,
                created_at,
                status,
                score,
                max_score,
                assignment_attempt_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            attempt["student_id"],
            task["task_id"],
            stored_answer,
            result["is_correct"],
            attempt_number,
            now,
            result["status"],
            result["score"],
            result["max_score"],
            assignment_attempt_id
        ))

        task_attempt_id = cursor.lastrowid

        if result["status"] == "checked":
            update_progress(
                conn,
                attempt["student_id"],
                task,
                result["score"],
                result["max_score"],
                now
            )

        created_attempts.append({
            "task_id": task["task_id"],
            "task_attempt_id": task_attempt_id,
            "status": result["status"],
            "score": result["score"],
            "max_score": result["max_score"],
            "is_correct": (
                bool(result["is_correct"])
                if result["is_correct"] is not None
                else None
            )
        })

    return created_attempts


def grade_assignment_attempt(
    conn,
    assignment_attempt_id: int,
    user_id: int,
    now: str
):
    """
    Проверяет ответы назначенной попытки.
    Вызывается из variants_routes.py внутри уже открытой транзакции.
    Создаёт task_attempts и обновляет прогресс только один раз.
    """
    attempt = get_assignment_attempt_for_checking(
        conn,
        assignment_attempt_id
    )

    if attempt["student_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail="Это не ваша попытка."
        )

    if attempt["status"] != "in_progress":
        raise HTTPException(
            status_code=409,
            detail="Эта попытка уже была отправлена."
        )

    return process_assignment_submission(
        conn,
        assignment_attempt_id
    )


# =========================================================
# SUBMIT ASSIGNMENT FOR CHECKING
# =========================================================

@router.post("/assignments/{assignment_attempt_id}/submit")
def submit_assignment_for_checking(
    assignment_attempt_id: int,
    current_user=Depends(get_current_user)
):
    """
    Внутренний этап завершения назначенной работы.

    Основной маршрут отправки:
    POST /api/assignments/{assignment_id}/submit

    Этот маршрут оставлен для внутренней интеграции
    и прямого завершения попытки через checking.
    """

    if current_user["role"] != "student":
        raise HTTPException(
            status_code=403,
            detail="Доступ разрешён только ученикам."
        )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        attempt = get_assignment_attempt_for_checking(
            conn,
            assignment_attempt_id
        )

        if attempt["student_id"] != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail="Это не ваша попытка."
            )

        if attempt["assignment_status"] != "active":
            raise HTTPException(
                status_code=409,
                detail="Назначенная работа закрыта."
            )

        created_attempts = process_assignment_submission(
            conn,
            assignment_attempt_id
        )

        submitted_at = now_iso()

        cursor = conn.execute("""
            UPDATE assignment_attempts
            SET status = 'submitted',
                submitted_at = ?
            WHERE id = ?
              AND status = 'in_progress'
        """, (
            submitted_at,
            assignment_attempt_id
        ))

        if cursor.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail="Попытка уже была отправлена."
            )

        finalize_assignment_attempt(
            conn,
            assignment_attempt_id
        )

        final_status = conn.execute("""
            SELECT status
            FROM assignment_attempts
            WHERE id = ?
        """, (
            assignment_attempt_id
        )).fetchone()["status"]

    return {
        "message": "Работа отправлена на проверку.",
        "assignment_attempt_id": assignment_attempt_id,
        "status": final_status,
        "submitted_at": submitted_at,
        "tasks": created_attempts
    }


# =========================================================
# REVIEW ACCESS
# =========================================================

def ensure_review_access(
    conn,
    attempt_id: int,
    current_user: dict
):
    """
    Администратор может проверять любые ответы.
    Учитель может проверять только назначенные им работы.
    Самостоятельная практика учителю недоступна.
    """

    attempt = conn.execute("""
        SELECT
            ta.*,
            aa.assignment_id,
            aa.student_id AS assignment_student_id,
            a.teacher_id AS assignment_teacher_id
        FROM task_attempts ta

        LEFT JOIN assignment_attempts aa
            ON aa.id = ta.assignment_attempt_id

        LEFT JOIN class_assignments a
            ON a.id = aa.assignment_id

        WHERE ta.id = ?
    """, (
        attempt_id
    )).fetchone()

    if attempt is None:
        raise HTTPException(
            status_code=404,
            detail="Попытка не найдена."
        )

    if current_user["role"] == "admin":
        return attempt

    if current_user["role"] == "teacher":
        if attempt["assignment_attempt_id"] is None:
            raise HTTPException(
                status_code=403,
                detail="Самостоятельная практика недоступна учителю."
            )

        if attempt["assignment_teacher_id"] != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail="Эта работа не принадлежит вашим назначениям."
            )

        return attempt

    raise HTTPException(
        status_code=403,
        detail="Недостаточно прав для проверки ответа."
    )


# =========================================================
# REVIEW QUEUE
# =========================================================

@router.get("/reviews/pending")
def get_pending_reviews(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user)
):
    if current_user["role"] not in ("admin", "teacher"):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав."
        )

    with get_connection() as conn:
        if current_user["role"] == "admin":
            where_sql = "a.status = 'pending_review'"
            params = []

        else:
            where_sql = """
                a.status = 'pending_review'
                AND a.assignment_attempt_id IS NOT NULL
                AND ca.teacher_id = ?
            """
            params = [current_user["id"]]

        rows = conn.execute(f"""
            SELECT
                a.id AS attempt_id,
                a.user_id,
                a.task_id,
                a.submitted_answer,
                a.attempt_number,
                a.created_at,
                a.max_score,
                a.assignment_attempt_id,

                t.subject_code,
                t.topic,
                t.question,
                t.task_type,

                ca.id AS assignment_id,
                ca.class_id,
                c.name AS class_name

            FROM task_attempts a

            JOIN tasks t
                ON t.id = a.task_id

            LEFT JOIN assignment_attempts aa
                ON aa.id = a.assignment_attempt_id

            LEFT JOIN class_assignments ca
                ON ca.id = aa.assignment_id

            LEFT JOIN classes c
                ON c.id = ca.class_id

            WHERE {where_sql}

            ORDER BY a.created_at ASC
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        total = conn.execute(f"""
            SELECT COUNT(*) AS total
            FROM task_attempts a

            LEFT JOIN assignment_attempts aa
                ON aa.id = a.assignment_attempt_id

            LEFT JOIN class_assignments ca
                ON ca.id = aa.assignment_id

            WHERE {where_sql}
        """, params).fetchone()["total"]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "reviews": [
            dict(row)
            for row in rows
        ]
    }


# =========================================================
# REVIEW DETAILS
# =========================================================

@router.get("/reviews/{attempt_id}")
def get_review_details(
    attempt_id: int,
    current_user=Depends(get_current_user)
):
    with get_connection() as conn:
        ensure_review_access(
            conn,
            attempt_id,
            current_user
        )

        row = conn.execute("""
            SELECT
                a.id AS attempt_id,
                a.user_id,
                a.task_id,
                a.submitted_answer,
                a.attempt_number,
                a.created_at,
                a.status,
                a.score,
                a.max_score,
                a.review_comment,
                a.reviewed_at,
                a.reviewed_by,
                a.assignment_attempt_id,

                t.subject_code,
                t.topic,
                t.question,
                t.answer AS reference_answer,
                t.explanation,
                t.task_type,
                t.checking_config_json,

                ca.id AS assignment_id,
                ca.class_id,
                c.name AS class_name

            FROM task_attempts a

            JOIN tasks t
                ON t.id = a.task_id

            LEFT JOIN assignment_attempts aa
                ON aa.id = a.assignment_attempt_id

            LEFT JOIN class_assignments ca
                ON ca.id = aa.assignment_id

            LEFT JOIN classes c
                ON c.id = ca.class_id

            WHERE a.id = ?
        """, (
            attempt_id
        )).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Попытка не найдена."
        )

    result = dict(row)

    config = parse_json(
        result.pop("checking_config_json"),
        {}
    )

    if not isinstance(config, dict):
        raise HTTPException(
            status_code=500,
            detail="Некорректная конфигурация проверки."
        )

    result["grading"] = get_grading_config(config)

    return result


# =========================================================
# MANUAL GRADING CORE
# =========================================================

def grade_attempt(
    conn,
    attempt_id: int,
    data: ReviewRequest,
    reviewer: str
):
    attempt = conn.execute("""
        SELECT *
        FROM task_attempts
        WHERE id = ?
    """, (
        attempt_id
    )).fetchone()

    if attempt is None:
        raise HTTPException(
            status_code=404,
            detail="Попытка не найдена."
        )

    if attempt["status"] != "pending_review":
        raise HTTPException(
            status_code=409,
            detail="Эта попытка уже проверена или не ожидает проверки."
        )

    task = conn.execute("""
        SELECT
            id,
            subject_code,
            topic,
            checking_config_json
        FROM tasks
        WHERE id = ?
    """, (
        attempt["task_id"]
    )).fetchone()

    if task is None:
        raise HTTPException(
            status_code=404,
            detail="Исходное задание не найдено."
        )

    config = parse_checking_config(task)
    grading = get_grading_config(config)
    criteria = grading.get("criteria", [])

    if criteria:
        if data.criterion_scores is None:
            raise HTTPException(
                status_code=422,
                detail="Необходимо передать баллы по критериям."
            )

        valid_criteria = {}
        criteria_max = 0.0

        for criterion in criteria:
            if not isinstance(criterion, dict):
                raise HTTPException(
                    status_code=500,
                    detail="Некорректно настроен критерий оценивания."
                )

            criterion_id = criterion.get("id")

            if not isinstance(criterion_id, str) or not criterion_id:
                raise HTTPException(
                    status_code=500,
                    detail="У критерия должен быть корректный ID."
                )

            criterion_max = validate_number(
                criterion.get("max_score"),
                f"max_score критерия {criterion_id}"
            )

            if criterion_max < 0:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Максимальный балл критерия "
                        "не может быть отрицательным."
                    )
                )

            if criterion_id in valid_criteria:
                raise HTTPException(
                    status_code=500,
                    detail="Обнаружены повторяющиеся ID критериев."
                )

            valid_criteria[criterion_id] = criterion_max
            criteria_max += criterion_max

        unknown = (
            set(data.criterion_scores.keys())
            - set(valid_criteria.keys())
        )

        if unknown:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Неизвестные критерии: "
                    f"{', '.join(sorted(unknown))}"
                )
            )

        score = 0.0

        for criterion_id, criterion_max in valid_criteria.items():
            value = validate_number(
                data.criterion_scores.get(criterion_id, 0),
                f"балл критерия {criterion_id}"
            )

            if value < 0 or value > criterion_max:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Некорректный балл по критерию "
                        f"{criterion_id}."
                    )
                )

            score += value

        max_score = criteria_max

        if not math.isclose(
            max_score,
            grading["max_score"],
            rel_tol=0,
            abs_tol=0.000001
        ):
            raise HTTPException(
                status_code=500,
                detail=(
                    "Сумма максимальных баллов критериев "
                    "не совпадает с grading.max_score."
                )
            )

    else:
        if data.score is None:
            raise HTTPException(
                status_code=422,
                detail="Для этого задания необходимо передать score."
            )

        score = validate_number(
            data.score,
            "score"
        )

        max_score = grading["max_score"]

        if score < 0 or score > max_score:
            raise HTTPException(
                status_code=422,
                detail="Набранный балл должен быть от 0 до максимального."
            )

    if not math.isfinite(score):
        raise HTTPException(
            status_code=422,
            detail="Некорректная сумма баллов."
        )

    fully_correct = is_fully_correct(
        score,
        max_score
    )

    is_correct = int(fully_correct)
    now = now_iso()

    cursor = conn.execute("""
        UPDATE task_attempts
        SET
            score = ?,
            max_score = ?,
            is_correct = ?,
            status = 'reviewed',
            review_comment = ?,
            reviewed_at = ?,
            reviewed_by = ?
        WHERE id = ?
          AND status = 'pending_review'
    """, (
        score,
        max_score,
        is_correct,
        data.comment,
        now,
        reviewer,
        attempt_id
    ))

    if cursor.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="Ответ уже был проверен."
        )

    update_progress(
        conn,
        attempt["user_id"],
        task,
        score,
        max_score,
        now
    )

    if attempt["assignment_attempt_id"] is not None:
        finalize_assignment_attempt(
            conn,
            attempt["assignment_attempt_id"]
        )

    return {
        "message": "Ответ проверен. Результат сохранён.",
        "attempt_id": attempt_id,
        "status": "reviewed",
        "score": score,
        "max_score": max_score,
        "is_correct": bool(is_correct),
        "comment": data.comment,
        "reviewed_by": reviewer,
        "reviewed_at": now
    }


# =========================================================
# MANUAL GRADING
# =========================================================

@router.post("/reviews/{attempt_id}/grade")
def grade_review(
    attempt_id: int,
    data: ReviewRequest,
    current_user=Depends(get_current_user)
):
    if current_user["role"] not in ("admin", "teacher"):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для проверки ответа."
        )

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        ensure_review_access(
            conn,
            attempt_id,
            current_user
        )

        result = grade_attempt(
            conn,
            attempt_id,
            data,
            current_user["username"]
        )

    return result


# =========================================================
# TEACHER: ASSIGNMENT RESULTS
# =========================================================

@router.get("/assignments/{assignment_id}/results")
def get_teacher_assignment_results(
    assignment_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        assignment = conn.execute("""
            SELECT
                id,
                class_id,
                teacher_id,
                variant_id,
                status
            FROM class_assignments
            WHERE id = ?
        """, (
            assignment_id
        )).fetchone()

        if assignment is None:
            raise HTTPException(
                status_code=404,
                detail="Назначенная работа не найдена."
            )

        if assignment["teacher_id"] != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail="У вас нет доступа к этой работе."
            )

        total_students = conn.execute("""
            SELECT COUNT(*) AS total
            FROM class_members
            WHERE class_id = ?
              AND status = 'active'
        """, (
            assignment["class_id"]
        )).fetchone()["total"]

        rows = conn.execute("""
            SELECT
                u.id AS student_id,
                u.username,

                aa.id AS assignment_attempt_id,
                aa.status AS attempt_status,
                aa.started_at,
                aa.submitted_at,

                COUNT(ta.id) AS checked_tasks,

                COALESCE(SUM(ta.score), 0) AS total_score,
                COALESCE(SUM(ta.max_score), 0) AS max_score,

                SUM(
                    CASE
                        WHEN ta.status = 'pending_review' THEN 1
                        ELSE 0
                    END
                ) AS pending_reviews

            FROM class_members cm

            JOIN auth_users u
                ON u.id = cm.student_id

            LEFT JOIN assignment_attempts aa
                ON aa.assignment_id = ?
               AND aa.student_id = u.id

            LEFT JOIN task_attempts ta
                ON ta.assignment_attempt_id = aa.id

            WHERE cm.class_id = ?
              AND cm.status = 'active'

            GROUP BY
                u.id,
                u.username,
                aa.id,
                aa.status,
                aa.started_at,
                aa.submitted_at

            ORDER BY u.username COLLATE NOCASE

            LIMIT ? OFFSET ?
        """, (
            assignment_id,
            assignment["class_id"],
            limit,
            offset
        )).fetchall()

        students = []

        for row in rows:
            students.append({
                "student_id": row["student_id"],
                "username": row["username"],
                "attempt": {
                    "id": row["assignment_attempt_id"],
                    "status": row["attempt_status"],
                    "started_at": row["started_at"],
                    "submitted_at": row["submitted_at"],
                    "checked_tasks": row["checked_tasks"],
                    "pending_reviews": row["pending_reviews"] or 0,
                    "total_score": row["total_score"],
                    "max_score": row["max_score"]
                } if row["assignment_attempt_id"] else None
            })

        submitted_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM assignment_attempts
            WHERE assignment_id = ?
              AND status IN ('submitted', 'reviewed')
        """, (
            assignment_id
        )).fetchone()["total"]

        in_progress_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM assignment_attempts
            WHERE assignment_id = ?
              AND status = 'in_progress'
        """, (
            assignment_id
        )).fetchone()["total"]

        reviewed_count = conn.execute("""
            SELECT COUNT(*) AS total
            FROM assignment_attempts
            WHERE assignment_id = ?
              AND status = 'reviewed'
        """, (
            assignment_id
        )).fetchone()["total"]

    return {
        "assignment_id": assignment_id,
        "statistics": {
            "total_students": total_students,
            "started_count": submitted_count + in_progress_count,
            "in_progress_count": in_progress_count,
            "submitted_count": submitted_count,
            "reviewed_count": reviewed_count,
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
# TEACHER: ASSIGNMENT ANSWERS
# =========================================================

@router.get(
    "/assignments/{assignment_id}/students/{student_id}/answers"
)
def get_student_assignment_answers(
    assignment_id: int,
    student_id: int,
    current_user=Depends(get_current_user)
):
    require_teacher(current_user)

    with get_connection() as conn:
        assignment = conn.execute("""
            SELECT id, teacher_id
            FROM class_assignments
            WHERE id = ?
        """, (
            assignment_id
        )).fetchone()

        if assignment is None:
            raise HTTPException(
                status_code=404,
                detail="Назначенная работа не найдена."
            )

        if assignment["teacher_id"] != current_user["id"]:
            raise HTTPException(
                status_code=403,
                detail="У вас нет доступа к этой работе."
            )

        attempt = conn.execute("""
            SELECT id, status, started_at, submitted_at
            FROM assignment_attempts
            WHERE assignment_id = ?
              AND student_id = ?
        """, (
            assignment_id,
            student_id
        )).fetchone()

        if attempt is None:
            raise HTTPException(
                status_code=404,
                detail="Ученик ещё не начинал эту работу."
            )

        rows = conn.execute("""
            SELECT
                ta.id AS attempt_id,
                ta.task_id,
                ta.submitted_answer,
                ta.status,
                ta.score,
                ta.max_score,
                ta.is_correct,
                ta.review_comment,
                ta.reviewed_at,
                ta.reviewed_by,

                t.question,
                t.topic,
                t.task_type

            FROM task_attempts ta

            JOIN tasks t
                ON t.id = ta.task_id

            WHERE ta.assignment_attempt_id = ?

            ORDER BY ta.id
        """, (
            attempt["id"]
        )).fetchall()

    return {
        "assignment_id": assignment_id,
        "student_id": student_id,
        "attempt": {
            "id": attempt["id"],
            "status": attempt["status"],
            "started_at": attempt["started_at"],
            "submitted_at": attempt["submitted_at"]
        },
        "answers": [
            dict(row)
            for row in rows
        ]
    }


# =========================================================
# INITIALIZATION
# =========================================================

init_checking_db()
