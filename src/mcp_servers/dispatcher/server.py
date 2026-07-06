"""A dispatcher MCP server for delegating jobs to subagents.

Manages job state in an SQLite database and asynchronously spawns subagents to handle them.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dispatcher")

DB_PATH = Path("~/.config/agents/dispatcher.db").expanduser()


def _init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
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


@mcp.tool()
def submit_job(worker_type: str, payload: str) -> str:
    """Submits a new job to the dispatcher.

    Args:
        worker_type: The type of worker to handle this job.
        payload: JSON string payload for the job.

    Returns:
        The newly generated job ID.
    """
    _init_db()
    job_id = str(uuid.uuid4())

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO jobs (id, status, worker_type, payload) VALUES (?, ?, ?, ?)",
            (job_id, "Running", worker_type, payload),
        )
        conn.commit()

    env = os.environ.copy()
    env["AGY_JOB_ID"] = job_id
    env["AGY_WORKER_TYPE"] = worker_type

    # Asynchronously spawn the worker
    subprocess.Popen(
        ["agy", f"--print={payload}"],
        start_new_session=True,
        env=env,
    )

    return job_id


@mcp.tool()
def get_job_status(job_id: str) -> str:
    """Gets the status of a specific job.

    Args:
        job_id: The ID of the job to check.

    Returns:
        JSON string representation of the job row.
    """
    _init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        row = cursor.fetchone()

    if not row:
        return json.dumps({"error": f"Job {job_id} not found."})

    return json.dumps(dict(row))


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
