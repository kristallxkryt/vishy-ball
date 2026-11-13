
"""
recommendations_routes.py
Улучшенная система персональных рекомендаций подготовки к ЕГЭ.
Проект: «Высший балл»
"""

import sqlite3

from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query

from auth_routes import get_current_user


DB_PATH = Path(__file__).resolve().parent / "users.db"

router = APIRouter(
    prefix="/api/profile",
    tags=["Персональные рекомендации"]
)

# Минимум уникальных заданий для статуса mastered.
MIN_TASKS_FOR_MASTERY = 3


# =========================================================
# DATABASE
# =========================================================

@contextmanager
def get_recommendations_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        yield conn
    finally:
        conn.close()


# =========================================================
# RECOMMENDATIONS
# =========================================================

@router.get("/recommendations")
def get_recommendations(
    subject_code: str | None = Query(
        default=None,
        min_length=2,
        max_length=30
    ),
    current_user=Depends(get_current_user)
):
    user_id = current_user["id"]

    # Считаем статистику непосредственно по завершённым попыткам.
    # pending_review не учитывается в точности и количестве решённых.
    query = """
        SELECT
            t.subject_code,
            t.topic,

            COUNT(DISTINCT t.id) AS available_tasks,

            COALESCE(a.total_answered, 0) AS total_answered,
            COALESCE(a.correct_answers, 0) AS correct_answers,

            COALESCE(a.answered_tasks, 0) AS answered_tasks,
            COALESCE(a.pending_reviews, 0) AS pending_reviews,
            COALESCE(a.pending_review_tasks, 0)
                AS pending_review_tasks

        FROM tasks t

        LEFT JOIN (
            SELECT
                t2.subject_code,
                t2.topic,

                COUNT(
                    CASE
                        WHEN ta.status IN ('checked', 'reviewed')
                         AND ta.is_correct IS NOT NULL
                        THEN 1
                    END
                ) AS total_answered,

                SUM(
                    CASE
                        WHEN ta.status IN ('checked', 'reviewed')
                         AND ta.is_correct = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS correct_answers,

                COUNT(
                    DISTINCT CASE
                        WHEN ta.status IN ('checked', 'reviewed')
                         AND ta.is_correct IS NOT NULL
                        THEN ta.task_id
                    END
                ) AS answered_tasks,

                SUM(
                    CASE
                        WHEN ta.status = 'pending_review' THEN 1
                        ELSE 0
                    END
                ) AS pending_reviews,

                COUNT(
                    DISTINCT CASE
                        WHEN ta.status = 'pending_review'
                        THEN ta.task_id
                    END
                ) AS pending_review_tasks

            FROM task_attempts ta

            JOIN tasks t2
                ON t2.id = ta.task_id

            WHERE ta.user_id = ?
              AND t2.is_active = 1
              AND (
                    (
                        ta.status IN ('checked', 'reviewed')
                        AND ta.is_correct IS NOT NULL
                    )
                    OR ta.status = 'pending_review'
              )

            GROUP BY
                t2.subject_code,
                t2.topic

        ) a
            ON a.subject_code = t.subject_code
            AND a.topic = t.topic

        WHERE t.is_active = 1
    """

    params = [user_id]

    if subject_code:
        query += " AND t.subject_code = ?"
        params.append(subject_code.strip().lower())

    query += """
        GROUP BY
            t.subject_code,
            t.topic,
            a.total_answered,
            a.correct_answers,
            a.answered_tasks,
            a.pending_reviews,
            a.pending_review_tasks

        ORDER BY
            t.subject_code,
            t.topic
    """

    try:
        with get_recommendations_connection() as conn:
            rows = conn.execute(query, params).fetchall()

    except sqlite3.Error:
        raise HTTPException(
            status_code=500,
            detail="Не удалось получить рекомендации."
        )

    recommendations = []

    priority_order = {
        "repeat_theory": 1,
        "start_topic": 2,
        "more_practice": 3,
        "consolidate": 4,
        "mastered": 5
    }

    # =====================================================
    # ANALYZE TOPICS
    # =====================================================

    for row in rows:
        available = row["available_tasks"]

        answered = row["total_answered"]
        correct = row["correct_answers"]

        answered_tasks = row["answered_tasks"]

        pending_reviews = row["pending_reviews"]
        pending_review_tasks = row["pending_review_tasks"]

        wrong = max(answered - correct, 0)

        remaining_tasks = max(
            available - answered_tasks,
            0
        )

        accuracy = (
            round(correct / answered * 100, 1)
            if answered > 0
            else 0
        )

        completion = (
            round(
                min(answered_tasks / available * 100, 100),
                1
            )
            if available > 0
            else 0
        )

        # -------------------------------------------------
        # NO COMPLETED ATTEMPTS
        # -------------------------------------------------

        if answered == 0 and pending_reviews > 0:
            status = "start_topic"
            title = "Ответы ожидают проверки"

            description = (
                "Ты уже отправил развёрнутый ответ. "
                "Он ожидает проверки преподавателем. "
                "После проверки статистика темы обновится."
            )

            action = "Дождаться проверки"

        elif answered == 0:
            status = "start_topic"
            title = "Начни изучение темы"

            description = (
                "Ты ещё не решил проверенных заданий по этой теме. "
                "Начни с теории и простых заданий."
            )

            action = "Начать решение заданий"

        # -------------------------------------------------
        # LOW ACCURACY
        # -------------------------------------------------

        elif accuracy < 50:
            status = "repeat_theory"
            title = "Повтори теорию"

            description = (
                "Пока много ошибок. Рекомендуем повторить "
                "теорию и внимательно разобрать решения."
            )

            action = "Повторить теорию"

        # -------------------------------------------------
        # MEDIUM ACCURACY
        # -------------------------------------------------

        elif accuracy < 80:
            status = "more_practice"
            title = "Продолжай практику"

            description = (
                "Основы уже усвоены, но пока встречаются ошибки. "
                "Реши дополнительные задания."
            )

            action = "Решить дополнительные задания"

        # -------------------------------------------------
        # GOOD ACCURACY, BUT NOT 100%
        # -------------------------------------------------

        elif accuracy < 100:
            status = "consolidate"
            title = "Закрепи знания"

            description = (
                "У тебя хороший результат. "
                "Потренируйся ещё, чтобы повысить точность."
            )

            action = "Закрепить знания"

        # -------------------------------------------------
        # ALL ANSWERS CORRECT, BUT TASKS REMAIN
        # -------------------------------------------------

        elif answered_tasks < available:
            status = "more_practice"
            title = "Реши оставшиеся задания"

            description = (
                "Все проверенные ответы пока правильные, "
                "но ты ещё не решил все доступные задания "
                "по этой теме."
            )

            action = "Продолжить решение заданий"

        # -------------------------------------------------
        # MASTERY
        # -------------------------------------------------

        elif answered_tasks >= MIN_TASKS_FOR_MASTERY:
            status = "mastered"
            title = "Тема освоена"

            description = (
                "Все доступные задания по этой теме решены, "
                "все проверенные ответы правильные, "
                "а количество разных заданий достаточно "
                "для подтверждения освоения темы. "
                "Можно переходить к следующей теме."
            )

            action = "Перейти к следующей теме"

        # -------------------------------------------------
        # NOT ENOUGH TASKS FOR MASTERY
        # -------------------------------------------------

        else:
            status = "consolidate"
            title = "Закрепи знания"

            description = (
                "Все доступные задания решены правильно, "
                "но в теме пока недостаточно разных заданий "
                "для подтверждения полного освоения. "
                "Вернись к теме позже для дополнительной практики."
            )

            action = "Закрепить знания"

        recommendations.append({
            "subject_code": row["subject_code"],
            "topic": row["topic"],

            "status": status,
            "priority": priority_order[status],

            "title": title,
            "description": description,
            "action": action,

            "available_tasks": available,
            "answered_tasks": answered_tasks,
            "remaining_tasks": remaining_tasks,
            "completion_percent": completion,

            "total_answered": answered,
            "correct_answers": correct,
            "wrong_answers": wrong,
            "accuracy_percent": accuracy,

            "pending_reviews": pending_reviews,
            "pending_review_tasks": pending_review_tasks
        })

    # =====================================================
    # SORT RECOMMENDATIONS
    # =====================================================

    recommendations.sort(
        key=lambda item: (
            item["priority"],
            -item["wrong_answers"],
            item["accuracy_percent"],
            item["subject_code"],
            item["topic"]
        )
    )

    # =====================================================
    # SUMMARY
    # =====================================================

    summary = {
        "total_topics": len(recommendations),

        "start_topics": 0,
        "repeat_topics": 0,
        "practice_topics": 0,
        "consolidate_topics": 0,
        "mastered_topics": 0,

        "total_available_tasks": 0,
        "total_answered_tasks": 0,
        "total_remaining_tasks": 0,

        "total_pending_reviews": 0,
        "total_pending_review_tasks": 0
    }

    status_counters = {
        "start_topic": "start_topics",
        "repeat_theory": "repeat_topics",
        "more_practice": "practice_topics",
        "consolidate": "consolidate_topics",
        "mastered": "mastered_topics"
    }

    for item in recommendations:
        counter = status_counters[item["status"]]
        summary[counter] += 1

        summary["total_available_tasks"] += (
            item["available_tasks"]
        )

        summary["total_answered_tasks"] += (
            item["answered_tasks"]
        )

        summary["total_remaining_tasks"] += (
            item["remaining_tasks"]
        )

        summary["total_pending_reviews"] += (
            item["pending_reviews"]
        )

        summary["total_pending_review_tasks"] += (
            item["pending_review_tasks"]
        )

    return {
        "user_id": user_id,
        "summary": summary,
        "recommendations": recommendations
    }
