from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

import duckdb

logger = logging.getLogger("mcp-memory.db")

DB_PATH = os.path.abspath(os.path.expanduser("~/.mcp/memory.db"))

# Cap on per-memory content length returned by recall/list_memories, so a single
# large synced memory (e.g. a 64 KB session log) cannot overflow the caller's
# context window. Mirrors the data server's MCP_DATA_MAX_CHARS. Set to 0 (or a
# non-positive value) to disable truncation.
MAX_CONTENT_CHARS_ENV = "MCP_MEMORY_MAX_CONTENT_CHARS"
DEFAULT_MAX_CONTENT_CHARS = 2000

# Schema initialization is serialized per database path so that concurrent write
# connections cannot race on ``CREATE TABLE`` and trigger a DuckDB catalog
# write-write conflict on a cold start.
_init_lock = threading.Lock()
_initialized_paths: set[str] = set()


def get_max_content_chars() -> int:
    """Return the configured per-memory content cap (0 disables truncation)."""
    raw = os.getenv(MAX_CONTENT_CHARS_ENV)
    if raw is None:
        return DEFAULT_MAX_CONTENT_CHARS
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; falling back to %d.",
            MAX_CONTENT_CHARS_ENV,
            raw,
            DEFAULT_MAX_CONTENT_CHARS,
        )
        return DEFAULT_MAX_CONTENT_CHARS
    return value if value > 0 else 0


def truncate_content(content: str) -> tuple[str, bool]:
    """Truncate ``content`` to the configured cap.

    Returns the (possibly shortened) text and whether truncation occurred.
    """
    limit = get_max_content_chars()
    if limit and len(content) > limit:
        return content[:limit], True
    return content, False


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize the schema if it does not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id VARCHAR PRIMARY KEY,
            key VARCHAR UNIQUE,
            content TEXT NOT NULL,
            category VARCHAR,
            tags VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # Create an index on key for faster lookups
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories (key);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories (category);")
    # Install the fts extension once (cached globally after the first run) and build
    # the BM25 index only if it is missing, so startup does not rebuild it every time.
    if _install_fts(conn) and not fts_index_exists(conn):
        rebuild_fts_index(conn)


def _install_fts(conn: duckdb.DuckDBPyConnection) -> bool:
    """Install and load the ``fts`` extension. Best-effort; returns availability.

    ``INSTALL`` is cached globally by DuckDB, so this is a no-op download after the
    first successful run. When the extension cannot be obtained — e.g. fully offline
    before it has been cached — this logs at debug level and returns False, and
    recall falls back to lexical token-overlap scoring. No content leaves the machine.
    """
    try:
        conn.execute("INSTALL fts;")
        conn.execute("LOAD fts;")
        return True
    except duckdb.Error as e:
        logger.debug("fts extension unavailable; recall will use lexical fallback: %s", e)
        return False


def fts_index_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    """Return whether the BM25 full-text index over ``memories`` has been built."""
    try:
        result = conn.execute(
            "SELECT count(*) FROM duckdb_schemas() WHERE schema_name = 'fts_main_memories'"
        ).fetchone()
        return bool(result and result[0])
    except duckdb.Error:
        return False


def rebuild_fts_index(conn: duckdb.DuckDBPyConnection) -> bool:
    """(Re)build the BM25 full-text search index over ``memories``. Best-effort.

    DuckDB's FTS index is a snapshot, so it is rebuilt after every write to stay
    current. Assumes the ``fts`` extension is already installed (init_db does that);
    only ``LOAD`` is issued here, not ``INSTALL``. Returns True when the index is
    available afterwards, False when the extension cannot be loaded.
    """
    try:
        conn.execute("LOAD fts;")
        conn.execute("PRAGMA create_fts_index('memories', 'id', 'content', 'key', overwrite=1);")
        return True
    except duckdb.Error as e:
        logger.debug("FTS index rebuild skipped (extension unavailable): %s", e)
        return False


def ensure_initialized(conn: duckdb.DuckDBPyConnection, db_path: str) -> None:
    """Run schema initialization once per database path, serialized across threads.

    Prevents concurrent write connections from racing on ``CREATE TABLE`` during
    a cold start, which DuckDB rejects with a catalog write-write conflict.
    """
    if db_path in _initialized_paths:
        return
    with _init_lock:
        if db_path in _initialized_paths:
            return
        init_db(conn)
        _initialized_paths.add(db_path)


def _open_connection(read_only: bool, max_retries: int) -> duckdb.DuckDBPyConnection:
    """Open a connection, retrying only connection/initialization-level contention.

    Retrying happens *before* the connection is handed to the caller, so it covers
    file-lock and cold-start catalog write-write/constraint conflicts. Errors raised
    later from the caller's query are NOT retried here — a @contextmanager generator
    cannot resume after an exception is thrown into its ``yield`` (that raises
    ``RuntimeError: generator didn't stop after throw()``); callers that need
    query-level retries must wrap their own operation.
    """
    last_err = None
    for attempt in range(max_retries):
        conn = None
        try:
            conn = duckdb.connect(database=DB_PATH, read_only=read_only)
            if not read_only:
                ensure_initialized(conn, DB_PATH)
            return conn
        except duckdb.Error as e:
            if conn is not None:
                conn.close()
            err_msg = str(e).lower()
            if (
                "lock" in err_msg
                or "permission" in err_msg
                or "resource temporarily unavailable" in err_msg
                or "conflict" in err_msg
                or "constraint" in err_msg
            ):
                last_err = e
                # Jittered exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s...
                sleep_time = (0.1 * (2**attempt)) + random.uniform(0.01, 0.05)
                logger.warning(
                    "Database contention (attempt %d/%d). Retrying in %.2fs. Error: %s",
                    attempt + 1,
                    max_retries,
                    sleep_time,
                    e,
                )
                time.sleep(sleep_time)
                continue
            raise

    raise RuntimeError(
        f"Database at {DB_PATH} is locked by another process and could not be accessed after {max_retries} attempts: {last_err}"
    )


@contextmanager
def get_db_conn(
    read_only: bool = False, max_retries: int = 5
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Yield a connection to the database, retrying connection-level contention.

    Ensures the parent directory exists. The retry loop wraps only opening and
    initializing the connection; exceptions raised inside the ``with`` body
    propagate to the caller unchanged.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if read_only and not os.path.exists(DB_PATH):
        read_only = False

    conn = _open_connection(read_only, max_retries)
    try:
        yield conn
    finally:
        conn.close()
