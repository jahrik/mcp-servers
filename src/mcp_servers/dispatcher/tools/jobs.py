from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

from ..models.schemas import GetJobStatusArgs, JobStatus, SubmitJobArgs, UpdateJobStatusArgs

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
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        # Migrate DBs created before the timestamp columns existed.
        for col in ("created_at", "updated_at"):
            with contextlib.suppress(sqlite3.OperationalError):
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT")
        conn.commit()


def submit_job(args: SubmitJobArgs) -> str:
    """Submits a new job to the dispatcher."""
    allow_spawn = os.environ.get("MCP_DISPATCHER_ALLOW_SPAWN", "").lower()
    if allow_spawn not in ("1", "true"):
        raise RuntimeError("Spawning is not allowed")

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
            "INSERT INTO jobs (id, status, worker_type, payload, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, JobStatus.RUNNING.value, args.worker_type, payload_str, now, now),
        )
        conn.commit()

    env = {k: v for k, v in os.environ.items() if k in {"PATH", "USER", "HOME", "LANG", "LC_ALL"}}
    env["AGY_JOB_ID"] = job_id
    env["AGY_WORKER_TYPE"] = args.worker_type
    env["MCP_DISPATCHER_DB_PATH"] = str(db_path)
    prompt = "You are a background worker. Read your AGY_WORKER_TYPE and AGY_JOB_ID from your environment variables. Fetch your job payload using the get_job_status tool for that job_id and execute the task. When finished, you must update the job status in the dispatcher DB."

    # Asynchronously spawn the worker
    try:
        subprocess.Popen(
            ["agy", f"--print={prompt}"],
            start_new_session=True,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
                (JobStatus.FAILED.value, _now(), job_id),
            )
            conn.commit()
        raise

    return job_id


def _fetch_job(db_path: Path, job_id: str) -> dict[str, object] | None:
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()
    if not row:
        return None
    job_data = dict(row)
    try:
        job_data["payload"] = json.loads(job_data["payload"])
    except json.JSONDecodeError:
        job_data["payload"] = {"error": "Invalid JSON in database"}
    return job_data


def get_job_status(args: GetJobStatusArgs) -> str:
    """Gets the status of a specific job."""
    _init_db()
    job_data = _fetch_job(get_db_path(), args.job_id)
    if job_data is None:
        return json.dumps({"error": f"Job {args.job_id} not found."})
    return json.dumps(job_data)


def update_job_status(args: UpdateJobStatusArgs) -> str:
    """Update a job's status (Running/Completed/Failed) and stamp updated_at.

    The path a spawned worker uses to report progress; the status is validated
    against the JobStatus enum so only known lifecycle states can be written.
    """
    _init_db()
    db_path = get_db_path()
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        # Guard the transition atomically: the WHERE clause refuses to touch a
        # row already in a terminal state, so two concurrent callers can't race
        # a SELECT/UPDATE window to clobber a terminal status. rowcount then
        # tells us whether anything changed.
        terminal = tuple(_TERMINAL_STATUSES)
        placeholders = ", ".join("?" for _ in terminal)
        cursor = conn.execute(
            f"UPDATE jobs SET status = ?, updated_at = ? "  # noqa: S608 — placeholders only
            f"WHERE id = ? AND status NOT IN ({placeholders})",
            (args.status.value, _now(), args.job_id, *terminal),
        )
        conn.commit()

        if cursor.rowcount == 0:
            # No row updated: the job is unknown, or it is already terminal.
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
