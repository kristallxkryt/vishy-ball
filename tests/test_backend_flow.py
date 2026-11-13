from pathlib import Path
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient

from main import app


DB_PATH = Path(__file__).resolve().parents[1] / "users.db"


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
        second_token = second_invite.json()["invite_url"].rsplit("/", 1)[-1]

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

        duplicate_join = client.post(
            "/api/classes/join",
            headers=student["headers"],
            json={"token": second_token},
        )
        assert duplicate_join.status_code == 409

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

        created_variant = client.post(
            "/api/variants",
            headers=teacher["headers"],
            json={
                "class_id": class_id,
                "name": "Проверочный вариант",
                "task_ids": [task_id],
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

        submitted = client.post(
            f"/api/assignments/{assignment_id}/submit",
            headers=student["headers"],
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "submitted"
        assert submitted.json()["grading"]["score"] == 1.0

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
        result_students = teacher_results.json()["students"]
        result_student = next(
            item for item in result_students
            if item["student_id"] == student["id"]
        )
        assert result_student["attempt"]["id"] == attempt_id
        assert result_student["attempt"]["score"] == 1.0

        # Самостоятельная практика ученика не раскрывается учителю.
        independent = client.post(
            "/api/checking/answer",
            headers=student["headers"],
            json={"task_id": task_id, "answer": "4"},
        )
        assert independent.status_code == 200, independent.text

        pending_reviews = client.get(
            "/api/checking/reviews/pending",
            headers=teacher["headers"],
        )
        assert pending_reviews.status_code == 200
        assert all(
            item["user_id"] != student["id"]
            or item["assignment_attempt_id"] is not None
            for item in pending_reviews.json()["reviews"]
        )
