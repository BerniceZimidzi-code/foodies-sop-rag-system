import json
import os
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
    password_hash: str,
    token_hash: str,
    expires_at: str,
) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, is_active = 0, must_change_password = 1,
                activation_token_hash = ?, activation_expires_at = ?,
                auth_version = auth_version + 1
            WHERE id = ?
            """,
            (password_hash, token_hash, expires_at, user_id),
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


def reset_user_password(user_id: str, password_hash: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 1,
                auth_version = auth_version + 1
            WHERE id = ?
            """,
            (password_hash, user_id),
        )
    return cursor.rowcount > 0


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
                auth_version = auth_version + 1
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
                activation_expires_at = CASE WHEN ? = 0 THEN NULL ELSE activation_expires_at END
            WHERE id = ?
            """,
            (int(is_active), int(is_active), int(is_active), user_id),
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
    expected_temporary_hash: str,
    password_hash: str,
) -> bool:
    now = _now()
    with connect() as connection:
        row = connection.execute(
            """
            SELECT id, password_hash FROM users
            WHERE activation_token_hash = ? AND activation_expires_at > ?
                AND is_active = 0
            """,
            (token_hash, now),
        ).fetchone()
        if row is None or row["password_hash"] != expected_temporary_hash:
            return False
        cursor = connection.execute(
            """
            UPDATE users
            SET password_hash = ?, is_active = 1, must_change_password = 0,
                auth_version = auth_version + 1,
                activation_token_hash = NULL, activation_expires_at = NULL
            WHERE id = ? AND activation_token_hash = ? AND is_active = 0
                AND activation_expires_at > ?
            """,
            (password_hash, row["id"], token_hash, now),
        )
    return cursor.rowcount == 1


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
) -> str:
    version_id = str(uuid.uuid4())
    try:
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO sops (
                    id, sop_id, title, department, owner, version, status,
                    effective_date, review_cycle_days, original_filename,
                    storage_path, content_sha256, uploaded_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending_review', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id, sop_id, title, department, owner, version,
                    effective_date, review_cycle_days, original_filename,
                    storage_path, content_sha256, uploaded_by, _now(),
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
    except sqlite3.IntegrityError as exc:
        if "sops.sop_id, sops.version" in str(exc).lower():
            raise ValueError("That SOP ID and version already exist.") from exc
        raise
    return version_id


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


def list_sop_versions(
    *,
    status_filter: str | None = None,
    department: str | None = None,
) -> list[dict[str, Any]]:
    clauses = []
    parameters: list[Any] = []
    if status_filter is not None:
        clauses.append("status = ?")
        parameters.append(status_filter)
    if department is not None:
        clauses.append("department = ? COLLATE NOCASE")
        parameters.append(department)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT s.*,
                   (SELECT COUNT(*) FROM sop_sections x
                    WHERE x.sop_version_id = s.id) AS section_count
            FROM sops s {where_clause}
            ORDER BY s.created_at DESC, s.rowid DESC
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


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
        if action in {"approve", "reject"}:
            if sop["status"] != "pending_review":
                raise ValueError("Only SOPs awaiting review can be approved or rejected.")
            if action == "approve":
                superseded = connection.execute(
                    "SELECT id FROM sops WHERE sop_id = ? AND status = 'approved'",
                    (sop["sop_id"],),
                ).fetchall()
                connection.execute(
                    """
                    UPDATE sops
                    SET status = 'archived', reviewed_by = ?, reviewed_at = ?
                    WHERE sop_id = ? AND status = 'approved'
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
