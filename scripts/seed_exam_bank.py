"""Idempotent loader for the authored EGE practice bank."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "bank" / "ege_2027_russian_seed.json"


def seed_exam_bank(db_path: str | Path | None = None) -> int:
    """Insert or update authored bank items without duplicating them."""
    import tasks_routes

    target = Path(db_path) if db_path else PROJECT_ROOT / "users.db"
    previous_db_path = tasks_routes.DB_PATH
    try:
        tasks_routes.DB_PATH = target
        tasks_routes.init_tasks_db()
    finally:
        tasks_routes.DB_PATH = previous_db_path

    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    conn = sqlite3.connect(target, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    changed = 0

    try:
        for task in payload["tasks"]:
            identity = (
                task["subject_code"],
                task["exam_number"],
                task["variant_label"],
                task["source"],
            )
            existing = conn.execute(
                """
                SELECT id FROM tasks
                WHERE subject_code = ?
                  AND exam_number = ?
                  AND variant_label = ?
                  AND source = ?
                """,
                identity,
            ).fetchone()

            values = (
                task["topic"],
                task["question"],
                task["answer"],
                task.get("hint"),
                task.get("explanation"),
                task.get("difficulty", "medium"),
                task["source"],
                task["task_type"],
                json.dumps(task.get("options", []), ensure_ascii=False),
                json.dumps(task.get("media", []), ensure_ascii=False),
                json.dumps(task["checking_config"], ensure_ascii=False),
            )

            if existing:
                conn.execute(
                    """
                    UPDATE tasks
                    SET topic = ?, question = ?, answer = ?, hint = ?,
                        explanation = ?, difficulty = ?, source = ?,
                        task_type = ?, options_json = ?, media_json = ?,
                        checking_config_json = ?, is_active = 1
                    WHERE id = ?
                    """,
                    (*values, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO tasks (
                        subject_code, topic, question, answer, hint,
                        explanation, difficulty, source, task_type,
                        options_json, media_json, checking_config_json,
                        exam_number, variant_label, is_active
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        task["subject_code"],
                        *values,
                        task["exam_number"],
                        task["variant_label"],
                    ),
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO topics (subject_code, name)
                VALUES (?, ?)
                """,
                (task["subject_code"], task["topic"]),
            )
            changed += 1

        conn.commit()
        return changed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load the authored EGE practice bank into SQLite."
    )
    parser.add_argument(
        "--db",
        default=str(PROJECT_ROOT / "users.db"),
        help="SQLite database path (defaults to users.db).",
    )
    args = parser.parse_args()
    count = seed_exam_bank(args.db)
    print(f"Обработано заданий: {count}")


if __name__ == "__main__":
    main()
