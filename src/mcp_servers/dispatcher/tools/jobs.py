from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import uuid
from pathlib import Path

from ..models.schemas import GetJobStatusArgs, SubmitJobArgs


def get_db_path() -> Path:
    # Default to ~/.mcp (alongside the github server's audit.db) rather than the
    # agent-config git clone at ~/.config/agents, where a runtime DB risks being
    # committed or clobbered on re-clone.
    path_str = os.environ.get("MCP_DISPATCHER_DB_PATH", "~/.mcp/dispatcher.db")
    return Path(path_str).expanduser()


def _init_db() -> None:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                worker_type TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
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

    _init_db()
    job_id = str(uuid.uuid4())
    db_path = get_db_path()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO jobs (id, status, worker_type, payload) VALUES (?, ?, ?, ?)",
            (job_id, "Running", args.worker_type, payload_str),
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
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE jobs SET status = ? WHERE id = ?",
                ("Failed", job_id),
            )
            conn.commit()
        raise

    return job_id


def get_job_status(args: GetJobStatusArgs) -> str:
    """Gets the status of a specific job."""
    _init_db()
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (args.job_id,))
        row = cursor.fetchone()

    if not row:
        return json.dumps({"error": f"Job {args.job_id} not found."})

    job_data = dict(row)
    try:
        job_data["payload"] = json.loads(job_data["payload"])
    except json.JSONDecodeError:
        job_data["payload"] = {"error": "Invalid JSON in database"}
    return json.dumps(job_data)
