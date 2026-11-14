"""
mock_exams_routes.py

Самостоятельные пробные варианты из банка заданий.
Попытки и ответы хранятся отдельно от обычной практики и работ класса.
"""

import json
import random
import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_routes import get_current_user
from checking_routes import (
    evaluate_answer,
    get_next_attempt_number,
    update_progress,
    get_connection,
)

router = APIRouter(prefix="/api/mock-exams", tags=["Пробные экзамены"])


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_mock_exam_tables():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mock_exam_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject_code TEXT NOT NULL,
                mode TEXT NOT NULL,
                variant_label TEXT,
                status TEXT NOT NULL DEFAULT 'in_progress',
                created_at TEXT NOT NULL,
                submitted_at TEXT,
                score REAL,
                max_score REAL,
                pending_review_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES auth_users(id) ON DELETE CASCADE,
                CHECK(mode IN ('preset', 'bank_mix')),
                CHECK(status IN ('in_progress', 'submitted'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mock_exam_attempt_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                exam_number INTEGER NOT NULL,
                position INTEGER NOT NULL,
                answer_json TEXT,
                result_json TEXT,
                FOREIGN KEY(attempt_id) REFERENCES mock_exam_attempts(id) ON DELETE CASCADE,
                FOREIGN KEY(task_id) REFERENCES tasks(id),
                UNIQUE(attempt_id, task_id),
                UNIQUE(attempt_id, position)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mock_exam_user_history
            ON mock_exam_attempts(user_id, subject_code, created_at DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_mock_exam_tasks_attempt
            ON mock_exam_attempt_tasks(attempt_id, position)
        """)


class GenerateMockExam(BaseModel):
    mode: str = Field(pattern="^(preset|bank_mix)$")
    variant_label: str | None = Field(default=None, min_length=1, max_length=150)


class SaveMockAnswer(BaseModel):
    answer: Any


def require_student(user):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Пробные экзамены доступны ученикам.")


def public_task(row):
    def parse(raw, fallback):
        try:
            return json.loads(raw) if raw is not None else fallback
        except (ValueError, TypeError):
            return fallback
    return {
        "id": row["id"],
        "subject_code": row["subject_code"],
        "topic": row["topic"],
        "question": row["question"],
        "difficulty": row["difficulty"],
        "task_type": row["task_type"],
        "exam_number": row["exam_number"],
        "variant_label": row["variant_label"],
        "options": parse(row["options_json"], []),
        "media": parse(row["media_json"], []),
    }


def get_attempt_or_404(conn, attempt_id, user_id):
    row = conn.execute("""
        SELECT * FROM mock_exam_attempts
        WHERE id = ? AND user_id = ?
    """, (attempt_id, user_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Пробный вариант не найден.")
    return row


def serialize_attempt(conn, attempt):
    rows = conn.execute("""
        SELECT mt.task_id, mt.exam_number, mt.position, mt.answer_json,
               mt.result_json, t.subject_code, t.topic, t.question,
               t.difficulty, t.task_type, t.options_json, t.media_json,
               t.variant_label
        FROM mock_exam_attempt_tasks mt
        JOIN tasks t ON t.id = mt.task_id
        WHERE mt.attempt_id = ?
        ORDER BY mt.position
    """, (attempt["id"],)).fetchall()
    tasks = []
    answered = 0
    for row in rows:
        answer = None
        result = None
        try:
            answer = json.loads(row["answer_json"]) if row["answer_json"] is not None else None
        except (ValueError, TypeError):
            answer = row["answer_json"]
        try:
            result = json.loads(row["result_json"]) if row["result_json"] else None
        except (ValueError, TypeError):
            result = None
        if row["answer_json"] is not None:
            answered += 1
        tasks.append({
            **public_task(row),
            "position": row["position"],
            "answer": answer if attempt["status"] == "in_progress" else None,
            "result": result,
        })
    return {
        "id": attempt["id"],
        "subject_code": attempt["subject_code"],
        "mode": attempt["mode"],
        "variant_label": attempt["variant_label"],
        "status": attempt["status"],
        "created_at": attempt["created_at"],
        "submitted_at": attempt["submitted_at"],
        "score": attempt["score"],
        "max_score": attempt["max_score"],
        "pending_review_count": attempt["pending_review_count"],
        "tasks_count": len(tasks),
        "answered_count": answered,
        "tasks": tasks,
    }


@router.get("/{subject_code}")
def get_mock_exam_catalog(subject_code: str, current_user=Depends(get_current_user)):
    require_student(current_user)
    code = subject_code.strip().lower()
    with get_connection() as conn:
        subject = conn.execute(
            "SELECT name FROM subjects WHERE subject_code = ? AND is_active = 1",
            (code,)
        ).fetchone()
        if subject is None:
            raise HTTPException(status_code=404, detail="Предмет не найден.")
        labels = conn.execute("""
            SELECT variant_label, COUNT(DISTINCT exam_number) AS numbers_count,
                   COUNT(*) AS tasks_count, MIN(id) AS first_task
            FROM tasks
            WHERE subject_code = ? AND is_active = 1
              AND exam_number IS NOT NULL AND variant_label IS NOT NULL
              AND TRIM(variant_label) != ''
            GROUP BY variant_label
            ORDER BY variant_label
        """, (code,)).fetchall()
        numbers = conn.execute("""
            SELECT exam_number, COUNT(*) AS tasks_count
            FROM tasks
            WHERE subject_code = ? AND is_active = 1 AND exam_number IS NOT NULL
            GROUP BY exam_number ORDER BY exam_number
        """, (code,)).fetchall()
        history = conn.execute("""
            SELECT id, mode, variant_label, status, created_at, submitted_at,
                   score, max_score, pending_review_count
            FROM mock_exam_attempts
            WHERE user_id = ? AND subject_code = ?
            ORDER BY id DESC
        """, (current_user["id"], code)).fetchall()
    return {
        "subject_code": code,
        "subject_name": subject["name"],
        "available_numbers": [
            {"exam_number": row["exam_number"], "tasks_count": row["tasks_count"]}
            for row in numbers
        ],
        "presets": [
            {
                "variant_label": row["variant_label"],
                "numbers_count": row["numbers_count"],
                "tasks_count": row["tasks_count"],
            }
            for row in labels
        ],
        "history": [dict(row) for row in history],
        "notice": "Состав определяется содержимым банка. Пока официальная спецификация предмета не привязана к банку, сборный вариант не считается гарантированно полным экзаменом."
    }


@router.post("/{subject_code}/generate", status_code=201)
def generate_mock_exam(
    subject_code: str,
    data: GenerateMockExam,
    current_user=Depends(get_current_user),
):
    require_student(current_user)
    code = subject_code.strip().lower()
    if data.mode == "preset" and not data.variant_label:
        raise HTTPException(status_code=422, detail="Для готового варианта укажи его название.")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        subject = conn.execute(
            "SELECT subject_code FROM subjects WHERE subject_code = ? AND is_active = 1",
            (code,)
        ).fetchone()
        if subject is None:
            raise HTTPException(status_code=404, detail="Предмет не найден.")
        if data.mode == "preset":
            rows = conn.execute("""
                SELECT id, exam_number
                FROM tasks
                WHERE subject_code = ? AND is_active = 1
                  AND exam_number IS NOT NULL AND variant_label = ?
                ORDER BY exam_number, id
            """, (code, data.variant_label)).fetchall()
            # У одного номера в пределах метки берём одно задание, без смешения вариантов.
            chosen = {}
            for row in rows:
                chosen.setdefault(row["exam_number"], row["id"])
            task_ids = [chosen[n] for n in sorted(chosen)]
            label = data.variant_label
            mode = "preset"
        else:
            rows = conn.execute("""
                SELECT id, exam_number
                FROM tasks
                WHERE subject_code = ? AND is_active = 1
                  AND exam_number IS NOT NULL
                ORDER BY exam_number, id
            """, (code,)).fetchall()
            groups = {}
            for row in rows:
                groups.setdefault(row["exam_number"], []).append(row["id"])
            if len(groups) < 2:
                raise HTTPException(
                    status_code=409,
                    detail="Для сборного варианта нужно не менее двух разных номеров заданий в банке."
                )
            task_ids = [random.choice(groups[number]) for number in sorted(groups)]
            label = None
            mode = "bank_mix"
        if len(task_ids) < 2:
            raise HTTPException(status_code=409, detail="В банке пока недостаточно заданий для варианта.")
        created = now_iso()
        cur = conn.execute("""
            INSERT INTO mock_exam_attempts
                (user_id, subject_code, mode, variant_label, status, created_at)
            VALUES (?, ?, ?, ?, 'in_progress', ?)
        """, (current_user["id"], code, mode, label, created))
        attempt_id = cur.lastrowid
        for position, task_id in enumerate(task_ids, start=1):
            exam_number = conn.execute(
                "SELECT exam_number FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()["exam_number"]
            conn.execute("""
                INSERT INTO mock_exam_attempt_tasks
                    (attempt_id, task_id, exam_number, position)
                VALUES (?, ?, ?, ?)
            """, (attempt_id, task_id, exam_number, position))
        attempt = get_attempt_or_404(conn, attempt_id, current_user["id"])
        payload = serialize_attempt(conn, attempt)
    return {"message": "Пробный вариант создан.", "attempt": payload}


@router.get("/attempts/{attempt_id}")
def get_mock_exam_attempt(attempt_id: int, current_user=Depends(get_current_user)):
    require_student(current_user)
    with get_connection() as conn:
        attempt = get_attempt_or_404(conn, attempt_id, current_user["id"])
        return {"attempt": serialize_attempt(conn, attempt)}


@router.put("/attempts/{attempt_id}/answers/{task_id}")
def save_mock_exam_answer(
    attempt_id: int,
    task_id: int,
    data: SaveMockAnswer,
    current_user=Depends(get_current_user),
):
    require_student(current_user)
    try:
        encoded = json.dumps(data.answer, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Не удалось сохранить ответ.")
    if len(encoded) > 50000:
        raise HTTPException(status_code=422, detail="Ответ слишком большой.")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        attempt = get_attempt_or_404(conn, attempt_id, current_user["id"])
        if attempt["status"] != "in_progress":
            raise HTTPException(status_code=409, detail="Пробный вариант уже отправлен.")
        cur = conn.execute("""
            UPDATE mock_exam_attempt_tasks SET answer_json = ?
            WHERE attempt_id = ? AND task_id = ?
        """, (encoded, attempt_id, task_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Задание не входит в этот вариант.")
        answered = conn.execute(
            "SELECT COUNT(*) AS n FROM mock_exam_attempt_tasks WHERE attempt_id = ? AND answer_json IS NOT NULL",
            (attempt_id,)
        ).fetchone()["n"]
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM mock_exam_attempt_tasks WHERE attempt_id = ?",
            (attempt_id,)
        ).fetchone()["n"]
    return {"message": "Ответ сохранён.", "answered_count": answered, "tasks_count": total}


@router.post("/attempts/{attempt_id}/submit")
def submit_mock_exam(attempt_id: int, current_user=Depends(get_current_user)):
    require_student(current_user)
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        attempt = get_attempt_or_404(conn, attempt_id, current_user["id"])
        if attempt["status"] != "in_progress":
            raise HTTPException(status_code=409, detail="Этот вариант уже отправлен.")
        rows = conn.execute("""
            SELECT mt.task_id, mt.answer_json, t.*
            FROM mock_exam_attempt_tasks mt
            JOIN tasks t ON t.id = mt.task_id
            WHERE mt.attempt_id = ?
            ORDER BY mt.position
        """, (attempt_id,)).fetchall()
        if not rows:
            raise HTTPException(status_code=409, detail="Вариант не содержит заданий.")
        missing = [row["task_id"] for row in rows if row["answer_json"] is None]
        if missing:
            raise HTTPException(
                status_code=409,
                detail={"message": "Ответь на все задания перед завершением.", "missing_count": len(missing)}
            )
        total_score = 0.0
        max_score = 0.0
        pending = 0
        now = now_iso()
        for row in rows:
            submitted = json.loads(row["answer_json"])
            result = evaluate_answer(row, submitted)
            if result["score"] is not None:
                total_score += float(result["score"])
            if result["max_score"] is not None:
                max_score += float(result["max_score"])
            if result["status"] == "pending_review":
                pending += 1
            task_attempt_number = get_next_attempt_number(conn, current_user["id"], row["task_id"])
            stored_answer = row["answer_json"]
            conn.execute("""
                INSERT INTO task_attempts (
                    user_id, task_id, submitted_answer, is_correct, attempt_number,
                    created_at, status, score, max_score, assignment_attempt_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """, (
                current_user["id"], row["task_id"], stored_answer,
                result["is_correct"], task_attempt_number, now,
                result["status"], result["score"], result["max_score"]
            ))
            if result["status"] == "checked":
                update_progress(conn, current_user["id"], row, result["score"], result["max_score"], now)
            conn.execute("""
                UPDATE mock_exam_attempt_tasks SET result_json = ?
                WHERE attempt_id = ? AND task_id = ?
            """, (json.dumps(result, ensure_ascii=False), attempt_id, row["task_id"]))
        conn.execute("""
            UPDATE mock_exam_attempts
            SET status = 'submitted', submitted_at = ?, score = ?,
                max_score = ?, pending_review_count = ?
            WHERE id = ?
        """, (now, round(total_score, 2), round(max_score, 2), pending, attempt_id))
        updated = get_attempt_or_404(conn, attempt_id, current_user["id"])
        payload = serialize_attempt(conn, updated)
    return {"message": "Пробный вариант завершён.", "attempt": payload}


init_mock_exam_tables()
