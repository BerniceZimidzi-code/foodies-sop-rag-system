import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator


APP_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(
    os.getenv("FOODIES_DATABASE_PATH", str(APP_ROOT / "data" / "foodies.sqlite3"))
)


@contextmanager
def connect() -> Generator[sqlite3.Connection, None, None]:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    with connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                department TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('staff', 'manager', 'admin')),
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                activation_token_hash TEXT,
                activation_expires_at TEXT,
                password_reset_token_hash TEXT,
                password_reset_expires_at TEXT,
                password_reset_requested_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                department TEXT NOT NULL,
                role TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                retrieved_sops TEXT NOT NULL,
                citations TEXT NOT NULL,
                success INTEGER NOT NULL CHECK (success IN (0, 1)),
                missing_sop INTEGER NOT NULL CHECK (missing_sop IN (0, 1)),
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at
                ON audit_logs (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id
                ON audit_logs (user_id);

            CREATE TABLE IF NOT EXISTS sops (
                id TEXT PRIMARY KEY,
                sop_id TEXT NOT NULL,
                title TEXT NOT NULL,
                department TEXT NOT NULL,
                owner TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending_review', 'approved', 'rejected', 'archived')
                ),
                effective_date TEXT NOT NULL,
                approved_by TEXT,
                approved_date TEXT,
                review_cycle_days INTEGER,
                original_filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                uploaded_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                reviewed_by TEXT,
                reviewed_at TEXT,
                review_note TEXT,
                UNIQUE (sop_id, version)
            );

            CREATE INDEX IF NOT EXISTS idx_sops_department_status
                ON sops (department, status);
            CREATE INDEX IF NOT EXISTS idx_sops_sop_id_status
                ON sops (sop_id, status);

            CREATE TABLE IF NOT EXISTS generated_sop_ids (
                sequence_name TEXT PRIMARY KEY,
                next_value INTEGER NOT NULL CHECK (next_value > 0)
            );

            CREATE TABLE IF NOT EXISTS document_categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                description TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS document_audit_events (
                id TEXT PRIMARY KEY,
                document_id TEXT,
                category_id TEXT,
                actor_id TEXT NOT NULL,
                actor_email TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_document_audit_created
                ON document_audit_events (created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_document_audit_document
                ON document_audit_events (document_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS failed_document_uploads (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                metadata TEXT NOT NULL,
                error TEXT NOT NULL,
                user_message TEXT NOT NULL DEFAULT '',
                uploaded_by_id TEXT NOT NULL,
                uploaded_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_failed_uploads_created
                ON failed_document_uploads (resolved_at, created_at DESC);

            CREATE TABLE IF NOT EXISTS sop_sections (
                id TEXT PRIMARY KEY,
                sop_version_id TEXT NOT NULL REFERENCES sops(id) ON DELETE CASCADE,
                heading TEXT NOT NULL,
                content TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                UNIQUE (sop_version_id, chunk_index)
            );

            CREATE INDEX IF NOT EXISTS idx_sop_sections_version
                ON sop_sections (sop_version_id, chunk_index);

            CREATE TABLE IF NOT EXISTS sop_events (
                id TEXT PRIMARY KEY,
                sop_version_id TEXT NOT NULL REFERENCES sops(id),
                actor_id TEXT NOT NULL,
                actor_email TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sop_events_version
                ON sop_events (sop_version_id, created_at DESC);
            """
        )
        user_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(users)")
        }
        if "must_change_password" not in user_columns:
            connection.execute(
                """
                ALTER TABLE users
                ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0
                    CHECK (must_change_password IN (0, 1))
                """
            )
        if "auth_version" not in user_columns:
            connection.execute(
                "ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0"
            )
        if "activation_token_hash" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN activation_token_hash TEXT")
        if "activation_expires_at" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN activation_expires_at TEXT")
        if "password_reset_token_hash" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN password_reset_token_hash TEXT")
        if "password_reset_expires_at" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN password_reset_expires_at TEXT")
        if "password_reset_requested_at" not in user_columns:
            connection.execute("ALTER TABLE users ADD COLUMN password_reset_requested_at TEXT")
        failed_upload_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(failed_document_uploads)")
        }
        if "user_message" not in failed_upload_columns:
            connection.execute(
                "ALTER TABLE failed_document_uploads "
                "ADD COLUMN user_message TEXT NOT NULL DEFAULT ''"
            )
        sop_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sops)")
        }
        existing_sops_need_category_migration = "category_id" not in sop_columns
        sop_migrations = {
            "category_id": "TEXT",
            "document_type": "TEXT NOT NULL DEFAULT 'SOP'",
            "location": "TEXT NOT NULL DEFAULT ''",
            "tags": "TEXT NOT NULL DEFAULT '[]'",
            "category_review_required": "INTEGER NOT NULL DEFAULT 1",
            "deleted_at": "TEXT",
            "status_before_delete": "TEXT",
            "permanently_deleted": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in sop_migrations.items():
            if column not in sop_columns:
                connection.execute(
                    f"ALTER TABLE sops ADD COLUMN {column} {definition}"
                )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_sops_category_status
                ON sops (category_id, status, deleted_at)
            """
        )
        seeded_categories = (
            "General Controls",
            "Store Operations",
            "Sales & Customer Service",
            "Quality",
            "Food Safety & Compliance",
            "Inventory & Stores",
            "Equipment & Asset Management",
            "Production & Kitchen Operations",
            "Cash & Finance",
        )
        now = _now()
        for name in seeded_categories:
            category_id = "category-" + _slug(name)
            connection.execute(
                """
                INSERT OR IGNORE INTO document_categories
                    (id, name, created_by, created_at, updated_at)
                VALUES (?, ?, 'system', ?, ?)
                """,
                (category_id, name, now, now),
            )
        if existing_sops_need_category_migration:
            for row in connection.execute(
                "SELECT DISTINCT department FROM sops WHERE category_id IS NULL"
            ):
                department = str(row["department"]).strip().casefold()
                category_name = {
                    "kitchen": "Production & Kitchen Operations",
                    "finance": "Cash & Finance",
                    "front of house": "Sales & Customer Service",
                    "quality": "Quality",
                    "food safety": "Food Safety & Compliance",
                    "inventory": "Inventory & Stores",
                    "stores": "Inventory & Stores",
                    "maintenance": "Equipment & Asset Management",
                }.get(department, "General Controls")
                connection.execute(
                    """
                    UPDATE sops SET category_id = ?, category_review_required = 0
                    WHERE category_id IS NULL AND department = ? COLLATE NOCASE
                    """,
                    ("category-" + _slug(category_name), row["department"]),
                )


def create_user(
    *,
    email: str,
    name: str,
    department: str,
    role: str,
    password_hash: str,
    is_active: bool = True,
    must_change_password: bool = False,
    activation_token_hash: str | None = None,
    activation_expires_at: str | None = None,
) -> str:
    user_id = str(uuid.uuid4())
    try:
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO users
                    (id, email, name, department, role, password_hash, is_active,
                     must_change_password, activation_token_hash, activation_expires_at,
                     created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email.strip().lower(),
                    name,
                    department,
                    role,
                    password_hash,
                    int(is_active),
                    int(must_change_password),
                    activation_token_hash,
                    activation_expires_at,
                    _now(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        if "users.email" in str(exc).lower():
            raise ValueError("A user with that email already exists.") from exc
        raise
    return user_id


def create_initial_admin(
    *,
    email: str,
    name: str,
    department: str,
    password_hash: str,
) -> bool:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            return False
        connection.execute(
            """
            INSERT INTO users
                (id, email, name, department, role, password_hash, is_active,
                 must_change_password, created_at)
            VALUES (?, ?, ?, ?, 'admin', ?, 1, 0, ?)
            """,
            (
                str(uuid.uuid4()),
                email.strip().lower(),
                name.strip(),
                department.strip(),
                password_hash,
                _now(),
            ),
        )
    return True


def list_document_categories(*, include_archived: bool = False) -> list[dict[str, Any]]:
    where_clause = "" if include_archived else "WHERE is_active = 1"
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT c.*,
                   (SELECT COUNT(*) FROM sops s WHERE s.category_id = c.id
                    AND s.deleted_at IS NULL AND s.permanently_deleted = 0) AS document_count
            FROM document_categories c {where_clause}
            ORDER BY c.name COLLATE NOCASE
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_document_category(category_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM document_categories WHERE id = ?", (category_id,)
        ).fetchone()
    return dict(row) if row else None


def create_document_category(
    *,
    name: str,
    description: str,
    actor_id: str,
    actor_email: str,
) -> dict[str, Any]:
    category_id = str(uuid.uuid4())
    now = _now()
    try:
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO document_categories
                    (id, name, description, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (category_id, name, description, actor_id, now, now),
            )
    except sqlite3.IntegrityError as exc:
        if "document_categories.name" in str(exc).lower():
            raise ValueError("A category with that name already exists.") from exc
        raise
    record_document_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="category_created",
        category_id=category_id,
        details={"name": name},
    )
    return get_document_category(category_id) or {}


def update_document_category(
    *,
    category_id: str,
    name: str,
    description: str,
    actor_id: str,
    actor_email: str,
) -> dict[str, Any] | None:
    current = get_document_category(category_id)
    if current is None:
        return None
    try:
        with connect() as connection:
            connection.execute(
                "UPDATE document_categories SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                (name, description, _now(), category_id),
            )
    except sqlite3.IntegrityError as exc:
        if "document_categories.name" in str(exc).lower():
            raise ValueError("A category with that name already exists.") from exc
        raise
    record_document_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="category_updated",
        category_id=category_id,
        details={
            "before": {"name": current["name"], "description": current["description"]},
            "after": {"name": name, "description": description},
        },
    )
    return get_document_category(category_id)


def set_document_category_active(
    *,
    category_id: str,
    is_active: bool,
    actor_id: str,
    actor_email: str,
) -> dict[str, Any] | None:
    current = get_document_category(category_id)
    if current is None:
        return None
    with connect() as connection:
        connection.execute(
            "UPDATE document_categories SET is_active = ?, updated_at = ? WHERE id = ?",
            (int(is_active), _now(), category_id),
        )
    record_document_event(
        actor_id=actor_id,
        actor_email=actor_email,
        action="category_restored" if is_active else "category_archived",
        category_id=category_id,
        details={"name": current["name"]},
    )
    return get_document_category(category_id)


def record_document_event(
    *,
    actor_id: str,
    actor_email: str,
    action: str,
    details: dict[str, Any],
    document_id: str | None = None,
    category_id: str | None = None,
) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO document_audit_events
                (id, document_id, category_id, actor_id, actor_email, action, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                document_id,
                category_id,
                actor_id,
                actor_email,
                action,
                json.dumps(details, ensure_ascii=False),
                _now(),
            ),
        )


def list_document_audit_events(
    *,
    limit: int = 100,
    query: str | None = None,
    action: str | None = None,
    document_id: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    parameters: list[Any] = []
    if action:
        clauses.append("e.action = ?")
        parameters.append(action)
    if document_id:
        clauses.append("e.document_id = ?")
        parameters.append(document_id)
    if query:
        clauses.append(
            "(e.actor_email LIKE ? OR e.action LIKE ? OR e.details LIKE ? "
            "OR s.title LIKE ? OR s.sop_id LIKE ? OR c.name LIKE ?)"
        )
        wildcard = f"%{query.strip()}%"
        parameters.extend([wildcard] * 6)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    parameters.append(max(1, min(limit, 500)))
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT e.*, s.sop_id, s.title AS document_title, c.name AS category_name
            FROM document_audit_events e
            LEFT JOIN sops s ON s.id = e.document_id
            LEFT JOIN document_categories c ON c.id = e.category_id
            {where_clause}
            ORDER BY e.created_at DESC, e.rowid DESC
            LIMIT ?
            """,
            parameters,
        ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["details"] = json.loads(event["details"])
        events.append(event)
    return events


def record_failed_document_upload(
    *,
    batch_id: str,
    original_filename: str,
    storage_path: str,
    content_sha256: str,
    metadata: dict[str, Any],
    error: str,
    user_message: str,
    uploaded_by_id: str,
    uploaded_by: str,
) -> str:
    attempt_id = str(uuid.uuid4())
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO failed_document_uploads
                (id, batch_id, original_filename, storage_path, content_sha256,
                 metadata, error, user_message, uploaded_by_id, uploaded_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt_id,
                batch_id,
                original_filename,
                storage_path,
                content_sha256,
                json.dumps(metadata, ensure_ascii=False),
                error,
                user_message,
                uploaded_by_id,
                uploaded_by,
                _now(),
            ),
        )
    return attempt_id


def list_failed_document_uploads() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, batch_id, original_filename, metadata, user_message,
                   uploaded_by, created_at, storage_path
            FROM failed_document_uploads
            WHERE resolved_at IS NULL
            ORDER BY created_at DESC, rowid DESC
            """
        ).fetchall()
    failures = []
    for row in rows:
        failure = dict(row)
        failure["metadata"] = json.loads(failure["metadata"])
        failure["metadata"].pop("location", None)
        if not failure["user_message"]:
            failure["user_message"] = (
                "Review the document details and try again, or choose a replacement file."
            )
        failure["has_original"] = bool(failure.pop("storage_path"))
        failures.append(failure)
    return failures


def get_failed_document_upload(attempt_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM failed_document_uploads WHERE id = ? AND resolved_at IS NULL",
            (attempt_id,),
        ).fetchone()
    if row is None:
        return None
    failure = dict(row)
    failure["metadata"] = json.loads(failure["metadata"])
    failure["metadata"].pop("location", None)
    return failure


def resolve_failed_document_upload(attempt_id: str) -> bool:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT storage_path FROM failed_document_uploads
            WHERE id = ? AND resolved_at IS NULL
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            return False
        cursor = connection.execute(
            """
            UPDATE failed_document_uploads SET resolved_at = ?
            WHERE id = ? AND resolved_at IS NULL
            """,
            (_now(), attempt_id),
        )
    if cursor.rowcount != 1:
        return False
    path = Path(row["storage_path"])
    if path.is_file():
        path.unlink(missing_ok=True)
    return True


def dismiss_failed_document_upload(attempt_id: str) -> str | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT storage_path FROM failed_document_uploads
            WHERE id = ? AND resolved_at IS NULL
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "UPDATE failed_document_uploads SET resolved_at = ? WHERE id = ?",
            (_now(), attempt_id),
        )
    path = Path(row["storage_path"])
    return str(path) if str(path) else None


def update_failed_document_upload(
    *,
    attempt_id: str,
    metadata: dict[str, Any],
    error: str,
    user_message: str,
) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE failed_document_uploads
            SET metadata = ?, error = ?, user_message = ?
            WHERE id = ? AND resolved_at IS NULL
            """,
            (
                json.dumps(metadata, ensure_ascii=False),
                error,
                user_message,
                attempt_id,
            ),
        )
    return cursor.rowcount == 1


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def get_existing_user_emails(emails: list[str]) -> set[str]:
    normalized = sorted({email.strip().lower() for email in emails if email.strip()})
    if not normalized:
        return set()
    placeholders = ",".join("?" for _ in normalized)
    with connect() as connection:
        rows = connection.execute(
            f"SELECT email FROM users WHERE email IN ({placeholders})",
            normalized,
        ).fetchall()
    return {str(row["email"]).casefold() for row in rows}


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_activation_token_hash(token_hash: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM users
            WHERE activation_token_hash = ? AND activation_expires_at > ?
                AND is_active = 0
            """,
            (token_hash, _now()),
        ).fetchone()
    return dict(row) if row else None


def update_activation_credentials(
    user_id: str,
    token_hash: str,
    expires_at: str,
) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET is_active = 0, must_change_password = 0,
                activation_token_hash = ?, activation_expires_at = ?,
                auth_version = auth_version + 1
            WHERE id = ?
            """,
            (token_hash, expires_at, user_id),
        )
    return cursor.rowcount == 1


def list_users() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, email, name, department, role, is_active,
                   must_change_password,
                   activation_token_hash IS NOT NULL AS activation_pending,
                   created_at
            FROM users ORDER BY email
            """
        ).fetchall()
    return [dict(row) for row in rows]


def issue_password_reset_for_email(
    email: str,
    token_hash: str,
    expires_at: str,
    requested_at: str,
    cooldown_before: str,
) -> dict[str, str] | None:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_reset_token_hash = ?, password_reset_expires_at = ?,
                password_reset_requested_at = ?
            WHERE email = ? AND is_active = 1
                AND (
                    password_reset_requested_at IS NULL
                    OR password_reset_requested_at <= ?
                )
            """,
            (
                token_hash,
                expires_at,
                requested_at,
                email.strip().lower(),
                cooldown_before,
            ),
        )
        if cursor.rowcount != 1:
            return None
        row = connection.execute(
            "SELECT id, email, name FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
    return dict(row) if row else None


def issue_password_reset_for_user(
    user_id: str,
    token_hash: str,
    expires_at: str,
    requested_at: str,
) -> dict[str, str] | None:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_reset_token_hash = ?, password_reset_expires_at = ?,
                password_reset_requested_at = ?
            WHERE id = ? AND is_active = 1
            """,
            (token_hash, expires_at, requested_at, user_id),
        )
        if cursor.rowcount != 1:
            return None
        row = connection.execute(
            "SELECT id, email, name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def get_user_by_password_reset_token_hash(token_hash: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM users
            WHERE password_reset_token_hash = ?
                AND password_reset_expires_at > ? AND is_active = 1
            """,
            (token_hash, _now()),
        ).fetchone()
    return dict(row) if row else None


def clear_password_reset_credentials(user_id: str, token_hash: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_reset_token_hash = NULL, password_reset_expires_at = NULL
            WHERE id = ? AND password_reset_token_hash = ?
            """,
            (user_id, token_hash),
        )
    return cursor.rowcount == 1


def consume_password_reset(
    token_hash: str,
    password_hash: str,
) -> dict[str, str] | None:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, email FROM users
            WHERE password_reset_token_hash = ?
                AND password_reset_expires_at > ? AND is_active = 1
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            return None
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 0,
                auth_version = auth_version + 1,
                password_reset_token_hash = NULL,
                password_reset_expires_at = NULL
            WHERE id = ? AND password_reset_token_hash = ?
                AND password_reset_expires_at > ? AND is_active = 1
            """,
            (password_hash, row["id"], token_hash, now),
        )
        if cursor.rowcount != 1:
            return None
    return {"id": str(row["id"]), "email": str(row["email"])}


def change_user_password(
    user_id: str,
    password_hash: str,
    expected_auth_version: int,
) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 0,
                auth_version = auth_version + 1,
                password_reset_token_hash = NULL,
                password_reset_expires_at = NULL
            WHERE id = ? AND must_change_password = 1 AND auth_version = ?
            """,
            (password_hash, user_id, expected_auth_version),
        )
    return cursor.rowcount > 0


def set_user_active(user_id: str, is_active: bool) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET is_active = ?, auth_version = auth_version + 1,
                activation_token_hash = CASE WHEN ? = 0 THEN NULL ELSE activation_token_hash END,
                activation_expires_at = CASE WHEN ? = 0 THEN NULL ELSE activation_expires_at END,
                password_reset_token_hash = CASE WHEN ? = 0 THEN NULL ELSE password_reset_token_hash END,
                password_reset_expires_at = CASE WHEN ? = 0 THEN NULL ELSE password_reset_expires_at END
            WHERE id = ?
            """,
            (
                int(is_active),
                int(is_active),
                int(is_active),
                int(is_active),
                int(is_active),
                user_id,
            ),
        )
    return cursor.rowcount > 0


def delete_user(user_id: str) -> bool:
    with connect() as connection:
        target = connection.execute(
            "SELECT role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if target is None:
            return False
        if target["role"] == "admin":
            remaining_admins = connection.execute(
                """
                SELECT COUNT(*) FROM users
                WHERE role = 'admin' AND is_active = 1 AND id != ?
                """,
                (user_id,),
            ).fetchone()[0]
            if remaining_admins == 0:
                raise ValueError("The last active administrator cannot be deleted.")
        connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return True


def activate_user(
    *,
    token_hash: str,
    password_hash: str,
) -> dict[str, str] | None:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, email FROM users
            WHERE activation_token_hash = ? AND activation_expires_at > ?
                AND is_active = 0
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            return None
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, is_active = 1, must_change_password = 0,
                auth_version = auth_version + 1,
                activation_token_hash = NULL, activation_expires_at = NULL,
                password_reset_token_hash = NULL, password_reset_expires_at = NULL
            WHERE id = ? AND activation_token_hash = ? AND is_active = 0
                AND activation_expires_at > ?
            """,
            (password_hash, row["id"], token_hash, now),
        )
        if cursor.rowcount != 1:
            return None
    return {"id": str(row["id"]), "email": str(row["email"])}


def record_audit_log(
    *,
    user_id: str,
    email: str,
    department: str,
    role: str,
    question: str,
    answer: str,
    retrieved_sops: list[str],
    citations: list[dict[str, Any]],
    success: bool,
    missing_sop: bool,
) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO audit_logs (
                id, user_id, email, department, role, question, answer,
                retrieved_sops, citations, success, missing_sop, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                user_id,
                email,
                department,
                role,
                question,
                answer,
                json.dumps(retrieved_sops),
                json.dumps(citations),
                int(success),
                int(missing_sop),
                _now(),
            ),
        )


def list_audit_logs(limit: int) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM audit_logs ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
    logs = []
    for row in rows:
        log = dict(row)
        log["retrieved_sops"] = json.loads(log["retrieved_sops"])
        log["citations"] = json.loads(log["citations"])
        log["success"] = bool(log["success"])
        log["missing_sop"] = bool(log["missing_sop"])
        logs.append(log)
    return logs


def create_sop_version(
    *,
    sop_id: str,
    title: str,
    department: str,
    owner: str,
    version: str,
    effective_date: str,
    review_cycle_days: int | None,
    original_filename: str,
    storage_path: str,
    content_sha256: str,
    uploaded_by: str,
    uploaded_by_id: str,
    sections: list[dict[str, str]],
    category_id: str | None = None,
    document_type: str = "SOP",
    tags: list[str] | None = None,
    category_review_required: bool = False,
) -> str:
    version_id = str(uuid.uuid4())
    try:
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO sops (
                    id, sop_id, title, department, owner, version, status,
                    effective_date, review_cycle_days, original_filename,
                    storage_path, content_sha256, uploaded_by, created_at,
                    category_id, document_type, tags, category_review_required
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?)
                """,
                (
                    version_id, sop_id, title, department, owner, version,
                    effective_date, review_cycle_days, original_filename,
                    storage_path, content_sha256, uploaded_by, _now(),
                    category_id, document_type, json.dumps(tags or []),
                    int(category_review_required),
                ),
            )
            connection.executemany(
                """
                INSERT INTO sop_sections (id, sop_version_id, heading, content, chunk_index)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        version_id,
                        section["heading"],
                        section["content"],
                        index,
                    )
                    for index, section in enumerate(sections)
                ],
            )
            connection.execute(
                """
                INSERT INTO sop_events
                    (id, sop_version_id, actor_id, actor_email, action, details, created_at)
                VALUES (?, ?, ?, ?, 'upload', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    version_id,
                    uploaded_by_id,
                    uploaded_by,
                    json.dumps({"filename": original_filename}),
                    _now(),
                ),
            )
            connection.execute(
                """
                INSERT INTO document_audit_events
                    (id, document_id, category_id, actor_id, actor_email,
                     action, details, created_at)
                VALUES (?, ?, ?, ?, ?, 'uploaded', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    version_id,
                    category_id,
                    uploaded_by_id,
                    uploaded_by,
                    json.dumps(
                        {
                            "filename": original_filename,
                            "category_review_required": category_review_required,
                        },
                        ensure_ascii=False,
                    ),
                    _now(),
                ),
            )
    except sqlite3.IntegrityError as exc:
        if "sops.sop_id, sops.version" in str(exc).lower():
            raise ValueError("That SOP ID and version already exist.") from exc
        raise
    return version_id


def next_generated_sop_id() -> str:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT next_value FROM generated_sop_ids WHERE sequence_name = 'default'"
        ).fetchone()
        if row is None:
            existing_ids = connection.execute(
                "SELECT sop_id FROM sops"
            ).fetchall()
            highest_value = max(
                (
                    int(match.group(1))
                    for existing in existing_ids
                    if (match := re.fullmatch(r"FD-SOP-(\d+)", existing["sop_id"], re.IGNORECASE))
                ),
                default=0,
            )
            next_value = highest_value + 1
        else:
            next_value = int(row["next_value"])
        while connection.execute(
            "SELECT 1 FROM sops WHERE sop_id = ? LIMIT 1",
            (f"FD-SOP-{next_value:06d}",),
        ).fetchone():
            next_value += 1
        if row is None:
            connection.execute(
                """
                INSERT INTO generated_sop_ids (sequence_name, next_value)
                VALUES ('default', ?)
                """,
                (next_value + 1,),
            )
        else:
            connection.execute(
                """
                UPDATE generated_sop_ids SET next_value = ?
                WHERE sequence_name = 'default'
                """,
                (next_value + 1,),
            )
    return f"FD-SOP-{next_value:06d}"


def get_sop_version(version_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM sops WHERE id = ?", (version_id,)
        ).fetchone()
    return dict(row) if row else None


def get_sop_sections(version_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT heading, content, chunk_index
            FROM sop_sections
            WHERE sop_version_id = ?
            ORDER BY chunk_index
            """,
            (version_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def find_sop_by_content_hash(content_sha256: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, sop_id, title, status
            FROM sops
            WHERE content_sha256 = ? AND deleted_at IS NULL
                AND permanently_deleted = 0
            LIMIT 1
            """,
            (content_sha256,),
        ).fetchone()
    return dict(row) if row else None


def update_sop_document_metadata(
    *,
    version_id: str,
    values: dict[str, Any],
    actor_id: str,
    actor_email: str,
) -> dict[str, Any] | None:
    allowed = {
        "title",
        "department",
        "owner",
        "version",
        "effective_date",
        "review_cycle_days",
        "category_id",
        "document_type",
        "tags",
    }
    changes = {key: value for key, value in values.items() if key in allowed}
    if "tags" in changes:
        changes["tags"] = json.dumps(changes["tags"], ensure_ascii=False)
    if not changes:
        return get_sop_version(version_id)
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM sops WHERE id = ? AND deleted_at IS NULL",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        before = dict(row)
        assignments = ", ".join(f"{column} = ?" for column in changes)
        connection.execute(
            f"""
            UPDATE sops SET {assignments},
                category_review_required = CASE WHEN ? IS NOT NULL
                    THEN 0 ELSE category_review_required END
            WHERE id = ?
            """,
            [
                *[
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, list)
                    else value
                    for value in changes.values()
                ],
                changes.get("category_id", before["category_id"]),
                version_id,
            ],
        )
        after = connection.execute(
            "SELECT * FROM sops WHERE id = ?", (version_id,)
        ).fetchone()
        now = _now()
        details = {
            key: {
                "before": json.loads(before[key]) if key == "tags" else before[key],
                "after": value,
            }
            for key, value in changes.items()
            if before[key] != (
                json.dumps(value, ensure_ascii=False)
                if key == "tags" and isinstance(value, list)
                else value
            )
        }
        connection.execute(
            """
            INSERT INTO document_audit_events
                (id, document_id, category_id, actor_id, actor_email, action, details, created_at)
            VALUES (?, ?, ?, ?, ?, 'metadata_updated', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                version_id,
            changes.get("category_id", before["category_id"]),
            actor_id,
            actor_email,
            json.dumps(details, ensure_ascii=False),
                now,
            ),
        )
        if "category_id" in changes and before["category_id"] != changes["category_id"]:
            connection.execute(
                """
                INSERT INTO document_audit_events
                    (id, document_id, category_id, actor_id, actor_email,
                     action, details, created_at)
                VALUES (?, ?, ?, ?, ?, 'category_moved', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    version_id,
                    changes["category_id"],
                    actor_id,
                    actor_email,
                    json.dumps(
                        {
                            "from_category_id": before["category_id"],
                            "to_category_id": changes["category_id"],
                        }
                    ),
                    now,
                ),
            )
    return dict(after)


def soft_delete_sop_version(
    *,
    version_id: str,
    actor_id: str,
    actor_email: str,
) -> dict[str, Any] | None:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM sops WHERE id = ? AND deleted_at IS NULL",
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        document = dict(row)
        connection.execute(
            """
            UPDATE sops SET deleted_at = ?, status_before_delete = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (now, document["status"], version_id),
        )
        connection.execute(
            """
            INSERT INTO document_audit_events
                (id, document_id, actor_id, actor_email, action, details, created_at)
            VALUES (?, ?, ?, ?, 'deleted', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                version_id,
                actor_id,
                actor_email,
                json.dumps({"soft_delete": True}),
                now,
            ),
        )
    return get_sop_version(version_id)


def restore_sop_version(
    *,
    version_id: str,
    actor_id: str,
    actor_email: str,
) -> dict[str, Any] | None:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM sops
            WHERE id = ? AND deleted_at IS NOT NULL AND permanently_deleted = 0
            """,
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        prior_status = row["status_before_delete"] or "archived"
        connection.execute(
            """
            UPDATE sops SET deleted_at = NULL, status = ?,
                status_before_delete = NULL
            WHERE id = ?
            """,
            (prior_status, version_id),
        )
        connection.execute(
            """
            INSERT INTO document_audit_events
                (id, document_id, actor_id, actor_email, action, details, created_at)
            VALUES (?, ?, ?, ?, 'restored', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                version_id,
                actor_id,
                actor_email,
                json.dumps({"restored_status": prior_status}),
                now,
            ),
        )
    return get_sop_version(version_id)


def permanently_purge_sop_version(
    *,
    version_id: str,
    actor_id: str,
    actor_email: str,
) -> dict[str, Any] | None:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM sops
            WHERE id = ? AND deleted_at IS NOT NULL AND permanently_deleted = 0
            """,
            (version_id,),
        ).fetchone()
        if row is None:
            return None
        document = dict(row)
        connection.execute("DELETE FROM sop_sections WHERE sop_version_id = ?", (version_id,))
        connection.execute(
            """
            UPDATE sops SET permanently_deleted = 1, storage_path = '',
                content_sha256 = '', status = 'archived'
            WHERE id = ?
            """,
            (version_id,),
        )
        connection.execute(
            """
            INSERT INTO document_audit_events
                (id, document_id, actor_id, actor_email, action, details, created_at)
            VALUES (?, ?, ?, ?, 'permanently_deleted', ?, ?)
            """,
            (
                str(uuid.uuid4()),
                version_id,
                actor_id,
                actor_email,
                json.dumps(
                    {
                        "original_filename": document["original_filename"],
                        "content_and_extracted_sections_removed": True,
                    }
                ),
                now,
            ),
        )
    return document


def list_sop_versions(
    *,
    status_filter: str | None = None,
    department: str | None = None,
    category_id: str | None = None,
    document_type: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    effective_before: str | None = None,
    effective_after: str | None = None,
    include_deleted: bool = False,
) -> list[dict[str, Any]]:
    clauses = []
    parameters: list[Any] = []
    if not include_deleted:
        clauses.append("s.deleted_at IS NULL")
    if status_filter is not None:
        clauses.append("s.status = ?")
        parameters.append(status_filter)
    if department is not None:
        clauses.append("s.department = ? COLLATE NOCASE")
        parameters.append(department)
    if category_id is not None:
        clauses.append("s.category_id = ?")
        parameters.append(category_id)
    if document_type is not None:
        clauses.append("s.document_type = ? COLLATE NOCASE")
        parameters.append(document_type)
    if tag is not None:
        clauses.append("s.tags LIKE ? COLLATE NOCASE")
        parameters.append(f'%"{tag.strip()}"%')
    if query is not None:
        clauses.append(
            "(s.title LIKE ? COLLATE NOCASE OR s.sop_id LIKE ? COLLATE NOCASE "
            "OR s.department LIKE ? COLLATE NOCASE OR s.tags LIKE ? COLLATE NOCASE "
            "OR s.original_filename LIKE ? COLLATE NOCASE "
            "OR c.name LIKE ? COLLATE NOCASE)"
        )
        wildcard = f"%{query.strip()}%"
        parameters.extend([wildcard] * 6)
    if effective_before is not None:
        clauses.append("s.effective_date <= ?")
        parameters.append(effective_before)
    if effective_after is not None:
        clauses.append("s.effective_date >= ?")
        parameters.append(effective_after)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT s.*, c.name AS category_name,
                   (SELECT COUNT(*) FROM sop_sections x
                    WHERE x.sop_version_id = s.id) AS section_count
            FROM sops s
            LEFT JOIN document_categories c ON c.id = s.category_id
            {where_clause}
            ORDER BY CASE WHEN s.deleted_at IS NULL THEN 0 ELSE 1 END,
                     s.created_at DESC, s.rowid DESC
            """,
            parameters,
        ).fetchall()
    documents = []
    for row in rows:
        document = dict(row)
        document.pop("location", None)
        try:
            document["tags"] = json.loads(document["tags"])
        except (TypeError, json.JSONDecodeError):
            document["tags"] = []
        document["category_review_required"] = bool(
            document["category_review_required"]
        )
        document["permanently_deleted"] = bool(document["permanently_deleted"])
        documents.append(document)
    return documents


def list_approved_sop_sections() -> list[dict[str, Any]]:
    today = datetime.now(timezone.utc).date().isoformat()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT s.sop_id, s.title, s.department, s.owner, s.version, s.status,
                   s.effective_date, s.approved_by, s.approved_date,
                   s.storage_path, x.heading AS section_heading,
                   x.content AS section_text
            FROM sops s
            JOIN sop_sections x ON x.sop_version_id = s.id
            WHERE s.status = 'approved' AND s.effective_date <= ?
                AND s.deleted_at IS NULL AND s.permanently_deleted = 0
            ORDER BY s.sop_id, s.effective_date DESC, s.version DESC, x.chunk_index
            """,
            (today,),
        ).fetchall()
    documents = []
    for row in rows:
        document = dict(row)
        document["source_path"] = str(
            Path(document.pop("storage_path")).relative_to(APP_ROOT)
        )
        documents.append(document)
    return documents


def transition_sop_version(
    *,
    version_id: str,
    action: str,
    actor_id: str,
    actor_email: str,
    review_note: str | None = None,
) -> dict[str, Any] | None:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM sops WHERE id = ?", (version_id,)
        ).fetchone()
        if row is None:
            return None

        sop = dict(row)
        if sop["deleted_at"] is not None or sop["permanently_deleted"]:
            raise ValueError("Deleted documents cannot be reviewed.")
        if action in {"approve", "reject"}:
            if sop["status"] != "pending_review":
                raise ValueError("Only SOPs awaiting review can be approved or rejected.")
            if action == "approve" and sop["category_review_required"]:
                raise ValueError("Assign an active category before approving this document.")
            if action == "approve":
                superseded = connection.execute(
                    """
                    SELECT id FROM sops WHERE sop_id = ? AND status = 'approved'
                        AND deleted_at IS NULL AND permanently_deleted = 0
                    """,
                    (sop["sop_id"],),
                ).fetchall()
                connection.execute(
                    """
                    UPDATE sops
                    SET status = 'archived', reviewed_by = ?, reviewed_at = ?
                    WHERE sop_id = ? AND status = 'approved'
                        AND deleted_at IS NULL AND permanently_deleted = 0
                    """,
                    (actor_id, now, sop["sop_id"]),
                )
                for previous in superseded:
                    connection.execute(
                        """
                        INSERT INTO sop_events
                            (id, sop_version_id, actor_id, actor_email, action, details, created_at)
                        VALUES (?, ?, ?, ?, 'archive', ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            previous["id"],
                            actor_id,
                            actor_email,
                            json.dumps({"superseded_by": version_id}),
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO document_audit_events
                            (id, document_id, category_id, actor_id, actor_email,
                             action, details, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            version_id,
                            sop["category_id"],
                            actor_id,
                            actor_email,
                            action,
                            json.dumps({"note": review_note} if review_note else {}),
                            now,
                        ),
                    )
                connection.execute(
                    """
                    UPDATE sops SET status = 'approved', approved_by = ?,
                        approved_date = ?, reviewed_by = ?, reviewed_at = ?,
                        review_note = ?
                    WHERE id = ?
                    """,
                    (
                        actor_email, now[:10], actor_id, now, review_note, version_id
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE sops SET status = 'rejected', reviewed_by = ?,
                        reviewed_at = ?, review_note = ?
                    WHERE id = ?
                    """,
                    (actor_id, now, review_note, version_id),
                )
        elif action == "archive":
            if sop["status"] != "approved":
                raise ValueError("Only approved SOP versions can be archived.")
            connection.execute(
                """
                UPDATE sops SET status = 'archived', reviewed_by = ?,
                    reviewed_at = ?, review_note = ?
                WHERE id = ?
                """,
                (actor_id, now, review_note, version_id),
            )
        else:
            raise ValueError("Unsupported SOP review action.")

        connection.execute(
            """
            INSERT INTO sop_events
                (id, sop_version_id, actor_id, actor_email, action, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                version_id,
                actor_id,
                actor_email,
                action,
                json.dumps({"note": review_note} if review_note else {}),
                now,
            ),
        )
        updated = connection.execute(
            "SELECT * FROM sops WHERE id = ?", (version_id,)
        ).fetchone()
    return dict(updated)


def list_sop_events(version_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT actor_id, actor_email, action, details, created_at
            FROM sop_events WHERE sop_version_id = ?
            ORDER BY created_at DESC, rowid DESC
            """,
            (version_id,),
        ).fetchall()
    events = []
    for row in rows:
        event = dict(row)
        event["details"] = json.loads(event["details"])
        events.append(event)
    return events


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
