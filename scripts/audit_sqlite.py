"""Read-only audit for SQLite files committed in the repository.

The script never prints account data, credentials, invite tokens, or email addresses.
It reports only integrity status and aggregate row counts.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATABASES = sorted(
    path
    for pattern in ("*.db", "*.sqlite", "*.sqlite3")
    for path in ROOT.glob(pattern)
)


def audit_database(path: Path) -> bool:
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)

    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_issues = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }

        counts = {}
        for table in ("auth_users", "auth_sessions", "tasks", "subjects",
                      "classes", "class_members", "class_invites",
                      "variants", "class_assignments", "task_attempts"):
            if table in tables:
                safe_table = table.replace('"', '""')
                counts[table] = connection.execute(
                    f'SELECT COUNT(*) FROM "{safe_table}"'
                ).fetchone()[0]

        invalid_password_hashes = 0
        if "auth_users" in tables:
            columns = {
                row[1]
                for row in connection.execute(
                    'PRAGMA table_info("auth_users")'
                ).fetchall()
            }
            if {"password_hash", "salt"}.issubset(columns):
                invalid_password_hashes = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM auth_users
                    WHERE length(password_hash) != 64
                       OR password_hash GLOB '*[^0-9a-fA-F]*'
                       OR length(salt) != 32
                       OR salt GLOB '*[^0-9a-fA-F]*'
                    """
                ).fetchone()[0]

        print(
            f"{path.name}: integrity={integrity}; "
            f"foreign_key_issues={len(foreign_key_issues)}; "
            f"invalid_password_hashes={invalid_password_hashes}; "
            f"rows={counts}"
        )

        return (
            integrity == "ok"
            and not foreign_key_issues
            and invalid_password_hashes == 0
        )
    finally:
        connection.close()


def main() -> int:
    if not DATABASES:
        print("No committed SQLite databases found.")
        return 0

    results = [audit_database(path) for path in DATABASES]
    if not all(results):
        print("SQLite release audit failed; inspect the database before release.")
        return 1

    print(f"SQLite release audit passed for {len(DATABASES)} database file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
