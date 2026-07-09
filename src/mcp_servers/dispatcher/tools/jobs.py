from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ..models.schemas import (
    ClaimJobArgs,
    CleanupJobsArgs,
    GetJobStatusArgs,
    GetMessagesArgs,
    JobStatus,
    ListJobsArgs,
    SendMessageArgs,
    SubmitJobArgs,
    UpdateJobStatusArgs,
)

# Cap the serialized payload so a single job can't bloat the row / DB unboundedly.
# Job payloads are task specs, not bulk data; 1 MiB is generous headroom.
MAX_PAYLOAD_BYTES = 1024 * 1024

_TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED.value, JobStatus.FAILED.value})


def get_db_path() -> Path:
    # Default to ~/.mcp (alongside the github server's audit.db) rather than the
    # agent-config git clone at ~/.config/agents, where a runtime DB risks being
    # committed or clobbered on re-clone.
    path_str = os.environ.get("MCP_DISPATCHER_DB_PATH", "~/.mcp/dispatcher.db")
    return Path(path_str).expanduser()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _init_db() -> None:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                worker_type TEXT NOT NULL,
                payload TEXT NOT NULL,
                result TEXT,
                claimed_by TEXT,
                parent_id TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                sender TEXT NOT NULL,
                recipient TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
            )
            """
        )
        # Migrate DBs created before the timestamp and new columns existed.
        for col in ("created_at", "updated_at", "result", "claimed_by", "parent_id"):
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        conn.commit()


def submit_job(args: SubmitJobArgs) -> str:
    """Submits a new job to the dispatcher queue."""
    try:
        payload_str = json.dumps(args.payload)
    except TypeError as e:
        raise ValueError("Payload must be JSON-serializable") from e

    payload_bytes = len(payload_str.encode("utf-8"))
    if payload_bytes > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"Payload is {payload_bytes} bytes, exceeds the {MAX_PAYLOAD_BYTES}-byte limit"
        )

    _init_db()
    job_id = str(uuid.uuid4())
    db_path = get_db_path()
    now = _now()

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO jobs (id, status, worker_type, payload, parent_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                JobStatus.QUEUED.value,
                args.worker_type,
                payload_str,
                args.parent_id,
                now,
                now,
            ),
        )
        conn.commit()

    return job_id


def claim_job(args: ClaimJobArgs) -> str:
    """Atomically claims the oldest Queued job for the given worker type."""
    _init_db()
    db_path = get_db_path()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.isolation_level = None
        conn.row_factory = sqlite3.Row
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.execute(
                "SELECT id FROM jobs WHERE status = ? AND worker_type = ? ORDER BY created_at ASC LIMIT 1",
                (JobStatus.QUEUED.value, args.worker_type),
            )
            row = cursor.fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return json.dumps({"job": None})

            job_id = row["id"]
            now = _now()
            conn.execute(
                "UPDATE jobs SET status = ?, claimed_by = ?, updated_at = ? WHERE id = ?",
                (JobStatus.RUNNING.value, args.agent_id, now, job_id),
            )
            conn.execute("COMMIT")

            job_data = _fetch_job(db_path, job_id)
            return json.dumps({"job": job_data})
        except Exception:
            conn.execute("ROLLBACK")
            raise


def _fetch_job(db_path: Path, job_id: str) -> dict[str, object] | None:
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
    if not row:
        return None
    job_data = dict(row)
    try:
        job_data["payload"] = json.loads(str(job_data["payload"]))
    except json.JSONDecodeError:
        job_data["payload"] = {"error": "Invalid JSON in database"}

    if job_data.get("result"):
        with contextlib.suppress(json.JSONDecodeError):
            job_data["result"] = json.loads(str(job_data["result"]))

    return job_data


def get_job_status(args: GetJobStatusArgs) -> str:
    """Gets the status of a specific job."""
    _init_db()
    job_data = _fetch_job(get_db_path(), args.job_id)
    if job_data is None:
        return json.dumps({"error": f"Job {args.job_id} not found."})
    return json.dumps(job_data)


def update_job_status(args: UpdateJobStatusArgs) -> str:
    """Update a job's status and optionally set result."""
    _init_db()
    db_path = get_db_path()

    result_str = None
    if args.result is not None:
        result_str = json.dumps(args.result)

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        terminal = tuple(_TERMINAL_STATUSES)
        placeholders = ", ".join("?" for _ in terminal)

        if result_str is not None:
            cursor = conn.execute(
                f"UPDATE jobs SET status = ?, result = ?, updated_at = ? "  # noqa: S608
                f"WHERE id = ? AND status NOT IN ({placeholders})",
                (args.status.value, result_str, _now(), args.job_id, *terminal),
            )
        else:
            cursor = conn.execute(
                f"UPDATE jobs SET status = ?, updated_at = ? "  # noqa: S608
                f"WHERE id = ? AND status NOT IN ({placeholders})",
                (args.status.value, _now(), args.job_id, *terminal),
            )
        conn.commit()

        if cursor.rowcount == 0:
            current = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (args.job_id,)
            ).fetchone()
            if current is None:
                return json.dumps({"error": f"Job {args.job_id} not found."})
            return json.dumps(
                {
                    "error": f"Job {args.job_id} is already {current[0]}; "
                    "terminal status is immutable."
                }
            )

    job_data = _fetch_job(db_path, args.job_id)
    return json.dumps(job_data)


def send_message(args: SendMessageArgs) -> str:
    """Append a message to a job's conversation history."""
    _init_db()
    db_path = get_db_path()
    msg_id = str(uuid.uuid4())
    now = _now()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO messages (id, job_id, sender, recipient, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, args.job_id, args.sender, args.recipient, args.content, now),
        )
        conn.commit()
    return json.dumps({"id": msg_id, "status": "sent"})


def get_messages(args: GetMessagesArgs) -> str:
    """Retrieve messages for a job."""
    _init_db()
    db_path = get_db_path()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        query = "SELECT * FROM messages WHERE job_id = ?"
        params: list[object] = [args.job_id]
        if args.since:
            query += " AND created_at > ?"
            params.append(args.since)
        query += " ORDER BY created_at ASC"
        cursor = conn.execute(query, tuple(params))
        rows = cursor.fetchall()
    return json.dumps([dict(row) for row in rows])


def list_jobs(args: ListJobsArgs) -> str:
    """Lists jobs, ordered by created_at DESC."""
    _init_db()
    db_path = get_db_path()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row

        query = "SELECT id, status, worker_type, created_at, updated_at FROM jobs"
        params: list[object] = []
        if args.status is not None:
            query += " WHERE status = ?"
            params.append(args.status.value)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(args.limit)

        cursor = conn.execute(query, tuple(params))
        rows = cursor.fetchall()

    return json.dumps([dict(row) for row in rows])


def cleanup_jobs(args: CleanupJobsArgs) -> str:
    """Delete terminal (Completed/Failed) jobs to bound table growth."""
    _init_db()
    db_path = get_db_path()

    terminal = tuple(_TERMINAL_STATUSES)
    placeholders = ", ".join("?" for _ in terminal)
    query = f"DELETE FROM jobs WHERE status IN ({placeholders})"  # noqa: S608
    params: list[object] = [*terminal]
    if args.older_than_days is not None:
        cutoff = (datetime.now(UTC) - timedelta(days=args.older_than_days)).isoformat()
        query += " AND updated_at < ?"
        params.append(cutoff)

    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        cursor = conn.execute(query, tuple(params))
        conn.commit()
        deleted = cursor.rowcount

    return json.dumps({"deleted": deleted})
