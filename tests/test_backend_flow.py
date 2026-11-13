from pathlib import Path
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from main import app
from auth_routes import create_session, get_connection, hash_password


DB_PATH = PROJECT_ROOT / "users.db"


def register_and_login(client: TestClient, role: str):
    suffix = uuid4().hex[:10]
    payload = {
        "username": f"{role}_{suffix}",
        "email": f"{role}_{suffix}@example.com",
        "password": "StrongPass123",
        "role": role,
    }

    registered = client.post("/api/auth/register", json=payload)
    assert registered.status_code == 201, registered.text

    logged_in = client.post(
        "/api/auth/login",
        json={
            "login": payload["username"],
            "password": payload["password"],
        },
    )
    assert logged_in.status_code == 200, logged_in.text

    return {
        "id": registered.json()["user"]["id"],
        "username": payload["username"],
        "headers": {
            "Authorization": f"Bearer {logged_in.json()['access_token']}"
        },
    }


def test_teacher_class_assignment_lifecycle():
    with TestClient(app) as client:
        teacher = register_and_login(client, "teacher")
        student = register_and_login(client, "student")
        unstarted_student = register_and_login(client, "student")
        outsider = register_and_login(client, "student")
        other_teacher = register_and_login(client, "teacher")

        # Публичная регистрация не должна позволять назначить admin.
        forbidden_admin = client.post(
            "/api/auth/register",
            json={
                "username": f"admin_{uuid4().hex[:10]}",
                "email": f"admin_{uuid4().hex[:10]}@example.com",
                "password": "StrongPass123",
                "role": "admin",
            },
        )
        assert forbidden_admin.status_code == 422

        created_class = client.post(
            "/api/classes",
            headers=teacher["headers"],
            json={
                "name": "Тестовый класс",
                "subject_code": "russian",
                "description": "Интеграционный тест",
            },
        )
        assert created_class.status_code == 201, created_class.text
        class_id = created_class.json()["class"]["id"]

        # Учитель не может управлять чужим классом.
        foreign_class = client.get(
            f"/api/classes/{class_id}",
            headers=other_teacher["headers"],
        )
        assert foreign_class.status_code == 403

        first_invite = client.post(
            f"/api/classes/{class_id}/invite",
            headers=teacher["headers"],
        )
        assert first_invite.status_code == 201, first_invite.text
        first_token = first_invite.json()["invite_url"].rsplit("/", 1)[-1]

        # Новое приглашение отзывает предыдущее.
        second_invite = client.post(
            f"/api/classes/{class_id}/invite",
            headers=teacher["headers"],
        )
        assert second_invite.status_code == 201, second_invite.text
        assert second_invite.json()["valid_days"] == 7
        second_token = second_invite.json()["invite_url"].rsplit("/", 1)[-1]

        with sqlite3.connect(DB_PATH) as connection:
            stored_token_hash = connection.execute(
                """
                SELECT token_hash
                FROM class_invites
                WHERE class_id = ?
                  AND revoked_at IS NULL
                """,
                (class_id,),
            ).fetchone()[0]
        assert stored_token_hash != second_token
        assert len(stored_token_hash) == 64

        expired_link = client.post(
            "/api/classes/join",
            headers=outsider["headers"],
            json={"token": first_token},
        )
        assert expired_link.status_code == 404

        joined = client.post(
            "/api/classes/join",
            headers=student["headers"],
            json={"token": second_token},
        )
        assert joined.status_code == 200, joined.text

        left_class = client.delete(
            f"/api/classes/{class_id}/leave",
            headers=student["headers"],
        )
        assert left_class.status_code == 200, left_class.text

        rejoined = client.post(
            "/api/classes/join",
            headers=student["headers"],
            json={"token": second_token},
        )
        assert rejoined.status_code == 200, rejoined.text

        duplicate_join = client.post(
            "/api/classes/join",
            headers=student["headers"],
            json={"token": second_token},
        )
        assert duplicate_join.status_code == 409

        unstarted_join = client.post(
            "/api/classes/join",
            headers=unstarted_student["headers"],
            json={"token": second_token},
        )
        assert unstarted_join.status_code == 200, unstarted_join.text

        # Создаём одно реальное задание для варианта.
        with sqlite3.connect(DB_PATH) as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    subject_code,
                    topic,
                    question,
                    answer,
                    task_type,
                    checking_config_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "russian",
                    "Интеграционная тема",
                    "Выбери правильный ответ: 2 + 2",
                    "4",
                    "text",
                    '{"grading":{"mode":"exact","max_score":1}}',
                ),
            )
            task_id = cursor.lastrowid
            manual_cursor = connection.execute(
                """
                INSERT INTO tasks (
                    subject_code,
                    topic,
                    question,
                    answer,
                    task_type,
                    checking_config_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "russian",
                    "Ручная проверка",
                    "Напиши развёрнутый ответ",
                    "",
                    "long_text",
                    '{"grading":{"mode":"manual","max_score":2}}',
                ),
            )
            manual_task_id = manual_cursor.lastrowid
            partial_cursor = connection.execute(
                """
                INSERT INTO tasks (
                    subject_code,
                    topic,
                    question,
                    answer,
                    task_type,
                    checking_config_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "russian",
                    "Частичные баллы",
                    "Выбери элементы",
                    "",
                    "text",
                    '{"grading":{"mode":"rules","max_score":2,"rules":[{"condition":{"type":"contains_all","value":["a"]},"score":1},{"condition":{"type":"contains_all","value":["a","b"]},"score":2}]}}',
                ),
            )
            partial_task_id = partial_cursor.lastrowid

        created_variant = client.post(
            "/api/variants",
            headers=teacher["headers"],
            json={
                "class_id": class_id,
                "name": "Проверочный вариант",
                "task_ids": [task_id, partial_task_id, manual_task_id],
            },
        )
        assert created_variant.status_code == 201, created_variant.text
        variant_id = created_variant.json()["variant"]["id"]

        # Ученик не имеет доступа к учительскому каталогу вариантов.
        student_variants = client.get(
            "/api/variants",
            headers=student["headers"],
        )
        assert student_variants.status_code == 403

        assignment = client.post(
            "/api/assignments",
            headers=teacher["headers"],
            json={"variant_id": variant_id},
        )
        assert assignment.status_code == 201, assignment.text
        assignment_id = assignment.json()["assignment"]["id"]

        # Посторонний ученик не может открыть назначение.
        outsider_access = client.get(
            f"/api/assignments/{assignment_id}",
            headers=outsider["headers"],
        )
        assert outsider_access.status_code == 403

        started = client.post(
            f"/api/assignments/{assignment_id}/start",
            headers=student["headers"],
        )
        assert started.status_code == 200, started.text
        attempt_id = started.json()["attempt"]["id"]

        # Закрываем работу после старта: начатую попытку всё ещё можно продолжить.
        closed = client.post(
            f"/api/assignments/{assignment_id}/close",
            headers=teacher["headers"],
        )
        assert closed.status_code == 200, closed.text

        # Ученик без начатой попытки больше не может открыть работу.
        unopened_details = client.get(
            f"/api/assignments/{assignment_id}",
            headers=unstarted_student["headers"],
        )
        assert unopened_details.status_code == 409

        unopened_start = client.post(
            f"/api/assignments/{assignment_id}/start",
            headers=unstarted_student["headers"],
        )
        assert unopened_start.status_code == 409

        visible_assignments = client.get(
            "/api/assignments",
            headers=student["headers"],
        )
        assert visible_assignments.status_code == 200
        assert any(
            item["id"] == assignment_id
            for item in visible_assignments.json()["assignments"]
        )

        saved = client.put(
            f"/api/assignments/{assignment_id}/answers/{task_id}",
            headers=student["headers"],
            json={"answer": "4"},
        )
        assert saved.status_code == 200, saved.text

        partial_saved = client.put(
            f"/api/assignments/{assignment_id}/answers/{partial_task_id}",
            headers=student["headers"],
            json={"answer": ["a"]},
        )
        assert partial_saved.status_code == 200, partial_saved.text

        manual_saved = client.put(
            f"/api/assignments/{assignment_id}/answers/{manual_task_id}",
            headers=student["headers"],
            json={"answer": "Развёрнутый ответ для преподавателя."},
        )
        assert manual_saved.status_code == 200, manual_saved.text

        submitted = client.post(
            f"/api/assignments/{assignment_id}/submit",
            headers=student["headers"],
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["grading"]["score"] == 2.0
        assert submitted.json()["grading"]["max_score"] == 5.0
        assert submitted.json()["grading"]["checked_count"] == 2
        assert submitted.json()["grading"]["pending_review_count"] == 1

        assigned_pending = client.get(
            "/api/checking/reviews/pending",
            headers=teacher["headers"],
        )
        assert assigned_pending.status_code == 200
        assigned_review = next(
            item for item in assigned_pending.json()["reviews"]
            if item["user_id"] == student["id"]
            and item["assignment_attempt_id"] == attempt_id
        )

        graded = client.post(
            f"/api/checking/reviews/{assigned_review['attempt_id']}/grade",
            headers=teacher["headers"],
            json={"score": 2, "comment": "Проверено по критериям."},
        )
        assert graded.status_code == 200, graded.text
        assert graded.json()["status"] == "reviewed"
        assert graded.json()["score"] == 2.0

        repeated_submit = client.post(
            f"/api/assignments/{assignment_id}/submit",
            headers=student["headers"],
        )
        assert repeated_submit.status_code == 409

        repeated_start = client.post(
            f"/api/assignments/{assignment_id}/start",
            headers=student["headers"],
        )
        assert repeated_start.status_code == 409

        teacher_results = client.get(
            f"/api/assignments/{assignment_id}/results",
            headers=teacher["headers"],
        )
        assert teacher_results.status_code == 200, teacher_results.text

        foreign_teacher_results = client.get(
            f"/api/assignments/{assignment_id}/results",
            headers=other_teacher["headers"],
        )
        assert foreign_teacher_results.status_code == 403

        result_students = teacher_results.json()["students"]
        result_student = next(
            item for item in result_students
            if item["student_id"] == student["id"]
        )
        assert result_student["attempt"]["id"] == attempt_id
        assert result_student["attempt"]["status"] == "reviewed"
        assert result_student["attempt"]["score"] == 4.0
        assert result_student["attempt"]["max_score"] == 5.0
        assert result_student["attempt"]["pending_review_count"] == 0

        with sqlite3.connect(DB_PATH) as connection:
            assigned_attempt_rows = connection.execute(
                """
                SELECT COUNT(*)
                FROM task_attempts
                WHERE assignment_attempt_id = ?
                """,
                (attempt_id,),
            ).fetchone()[0]
            progress_total = connection.execute(
                """
                SELECT COALESCE(SUM(total_answered), 0)
                FROM user_progress
                WHERE user_id = ?
                """,
                (student["id"],),
            ).fetchone()[0]

        assert assigned_attempt_rows == 3
        assert progress_total == 3

        # Самостоятельный развёрнутый ответ ожидает проверки,
        # но учитель не должен видеть его в своей очереди.
        independent = client.post(
            "/api/checking/answer",
            headers=student["headers"],
            json={
                "task_id": manual_task_id,
                "answer": "Это мой самостоятельный развёрнутый ответ.",
            },
        )
        assert independent.status_code == 200, independent.text
        assert independent.json()["status"] == "pending_review"

        with sqlite3.connect(DB_PATH) as connection:
            progress_totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(total_answered), 0),
                    COALESCE(SUM(total_score), 0),
                    COALESCE(SUM(max_score), 0)
                FROM user_progress
                WHERE user_id = ?
                """,
                (student["id"],),
            ).fetchone()

        # Ожидающая ручной проверки самостоятельная работа
        # пока не должна менять личную статистику.
        assert progress_totals == (3, 4.0, 5.0)

        private_review = client.get(
            f"/api/checking/reviews/{independent.json()['attempt_id']}",
            headers=teacher["headers"],
        )
        assert private_review.status_code == 403

        pending_reviews = client.get(
            "/api/checking/reviews/pending",
            headers=teacher["headers"],
        )
        assert pending_reviews.status_code == 200
        assert all(
            item["user_id"] != student["id"]
            for item in pending_reviews.json()["reviews"]
        )

        # Проверяем административную аналитику и разграничение доступа.
        admin_salt = os.urandom(16)
        with get_connection() as connection:
            admin_cursor = connection.execute(
                """
                INSERT INTO auth_users (
                    username,
                    email,
                    password_hash,
                    salt,
                    created_at,
                    role,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, 'admin', 1)
                """,
                (
                    f"admin_{uuid4().hex[:10]}",
                    f"admin_{uuid4().hex[:10]}@example.com",
                    hash_password("AdminStrongPass123", admin_salt),
                    admin_salt.hex(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            admin_id = admin_cursor.lastrowid

        admin_token = create_session(admin_id)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        overview = client.get(
            "/api/admin/analytics/overview",
            headers=admin_headers,
        )
        assert overview.status_code == 200, overview.text
        assert overview.json()["users"]["teachers"] >= 2
        assert overview.json()["users"]["students"] >= 3
        assert overview.json()["users"]["admins"] == 1
        assert overview.json()["reviews"]["pending"] == 1

        # Проверяем рейтинг учеников и аналитику проблемных тем.
        student_analytics = client.get(
            "/api/admin/analytics/students",
            headers=admin_headers,
        )
        assert student_analytics.status_code == 200, student_analytics.text
        ranked_student = next(
            item for item in student_analytics.json()["students"]
            if item["user_id"] == student["id"]
        )
        assert ranked_student["total_attempts"] == 3
        assert ranked_student["total_score"] == 4.0
        assert ranked_student["max_score"] == 5.0
        assert ranked_student["pending_reviews"] == 1

        problem_topics = client.get(
            "/api/admin/analytics/problem-topics",
            headers=admin_headers,
        )
        assert problem_topics.status_code == 200, problem_topics.text
        assert any(
            item["topic"] == "Частичные баллы"
            and item["wrong_attempts"] == 1
            for item in problem_topics.json()["topics"]
        )

        forbidden_teacher_analytics = client.get(
            "/api/admin/analytics/overview",
            headers=teacher["headers"],
        )
        assert forbidden_teacher_analytics.status_code == 403

        admin_user_list = client.get(
            "/api/users",
            headers=admin_headers,
        )
        assert admin_user_list.status_code == 200

        forbidden_teacher_user_list = client.get(
            "/api/users",
            headers=teacher["headers"],
        )
        assert forbidden_teacher_user_list.status_code == 403

        removed_member = client.delete(
            f"/api/classes/{class_id}/members/{student['id']}",
            headers=teacher["headers"],
        )
        assert removed_member.status_code == 200, removed_member.text

        former_student_access = client.get(
            f"/api/assignments/{assignment_id}",
            headers=student["headers"],
        )
        assert former_student_access.status_code == 403

        historical_results = client.get(
            f"/api/assignments/{assignment_id}/results",
            headers=teacher["headers"],
        )
        assert historical_results.status_code == 200
        assert any(
            item["student_id"] == student["id"]
            for item in historical_results.json()["students"]
        )

        # Финальная проверка целостности SQLite после полного сценария.
        with get_connection() as connection:
            foreign_key_errors = connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
            tables = {
                row["name"]
                for row in connection.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchall()
            }

        assert foreign_key_errors == []
        assert {
            "auth_users",
            "auth_sessions",
            "subjects",
            "tasks",
            "user_progress",
            "classes",
            "class_members",
            "class_invites",
            "variants",
            "variant_tasks",
            "class_assignments",
            "assignment_attempts",
            "assignment_answers",
            "task_attempts",
        }.issubset(tables)



def test_expired_session_is_rejected_and_removed():
    with TestClient(app) as client:
        student = register_and_login(client, "student")

        token = student["headers"]["Authorization"].split(" ", 1)[1]
        import hashlib

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expired_at = (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat()

        with get_connection() as connection:
            connection.execute(
                """
                UPDATE auth_sessions
                SET expires_at = ?
                WHERE token_hash = ?
                """,
                (expired_at, token_hash),
            )

        rejected = client.get(
            "/api/auth/me",
            headers=student["headers"],
        )
        assert rejected.status_code == 401

        with get_connection() as connection:
            remaining = connection.execute(
                "SELECT 1 FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()

        assert remaining is None
