from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import duckdb

logger = logging.getLogger("mcp-memory.db")

DB_PATH = os.path.abspath(os.path.expanduser("~/.mcp/memory.db"))


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize the schema if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id VARCHAR PRIMARY KEY,
            key VARCHAR,
            content TEXT NOT NULL,
            category VARCHAR,
            tags VARCHAR,
            embedding FLOAT[],
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Create an index on key for faster lookups
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories (key);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories (category);")


@contextmanager
def get_db_conn(
    read_only: bool = False, max_retries: int = 5
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Yield a connection to the database, retrying if the database is locked.

    Ensures the parent directory exists.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    last_err = None

    for attempt in range(max_retries):
        try:
            # Connect to DuckDB (using read_only if requested)
            conn = duckdb.connect(database=DB_PATH, read_only=read_only)
            try:
                if not read_only:
                    init_db(conn)
                yield conn
            finally:
                conn.close()
            return
        except (duckdb.IOException, duckdb.ConnectionException) as e:
            err_msg = str(e).lower()
            if (
                "lock" in err_msg
                or "permission" in err_msg
                or "resource temporarily unavailable" in err_msg
            ):
                last_err = e
                # Jittered exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s...
                sleep_time = (0.1 * (2**attempt)) + random.uniform(0.01, 0.05)
                logger.warning(
                    "Database locked (attempt %d/%d). Retrying in %.2fs. Error: %s",
                    attempt + 1,
                    max_retries,
                    sleep_time,
                    e,
                )
                time.sleep(sleep_time)
                continue
            raise e

    raise RuntimeError(
        f"Database at {DB_PATH} is locked by another process and could not be accessed after {max_retries} attempts: {last_err}"
    )


def execute_query(
    query: str, params: list[Any] | None = None, read_only: bool = False
) -> list[tuple[Any, ...]]:
    """Helper to execute a query and return all results under retry lock protection."""
    with get_db_conn(read_only=read_only) as conn:
        if params is not None:
            res = conn.execute(query, params).fetchall()
        else:
            res = conn.execute(query).fetchall()
        return res
