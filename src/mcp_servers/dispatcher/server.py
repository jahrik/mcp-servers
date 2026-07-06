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

from .models.schemas import GetJobStatusArgs, SubmitJobArgs

mcp = FastMCP("dispatcher")


def get_db_path() -> Path:
    path_str = os.environ.get("MCP_DISPATCHER_DB_PATH", "~/.config/agents/dispatcher.db")
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


@mcp.tool()
def submit_job(args: SubmitJobArgs) -> str:
    """Submits a new job to the dispatcher."""
    if os.environ.get("MCP_DISPATCHER_ALLOW_SPAWN") != "true":
        raise RuntimeError("Spawning is not allowed")

    payload_str = json.dumps(args.payload)

    _init_db()
    job_id = str(uuid.uuid4())
    db_path = get_db_path()

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO jobs (id, status, worker_type, payload) VALUES (?, ?, ?, ?)",
            (job_id, "Running", args.worker_type, payload_str),
        )
        conn.commit()

    env = os.environ.copy()
    env["AGY_JOB_ID"] = job_id
    env["AGY_WORKER_TYPE"] = args.worker_type
    env["MCP_DISPATCHER_DB_PATH"] = str(db_path)

    # Asynchronously spawn the worker
    try:
        subprocess.Popen(
            ["agy", f"--print={payload_str}"],
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


@mcp.tool()
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

    return json.dumps(dict(row))


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
