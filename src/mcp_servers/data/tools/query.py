from __future__ import annotations

import asyncio
import decimal
import json
import math
import os
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Any

import duckdb

from ..models.schemas import DuckDbCloseDatabaseArgs, DuckDbQueryArgs

# Total output budget (chars). max_rows caps rows, not bytes — a wide text
# column can still blow the context window, so the rendered JSON is capped too.
DEFAULT_MAX_CHARS = 100_000


class DuckDbJSONEncoder(json.JSONEncoder):
    """Serialize DuckDB's richer types; stringify anything unknown rather than fail.

    A data tool should return a readable value for every cell — UUID, INTERVAL
    (timedelta), TIME, and any type not anticipated fall back to str().
    """

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date, time)):
            return o.isoformat()
        if isinstance(o, decimal.Decimal):
            # Lossy above ~15 significant digits; documented in docs/data.md.
            return float(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", errors="replace")
        return str(o)


def _json_safe(value: Any) -> Any:
    """Replace non-finite floats: json.dumps would emit NaN/Infinity, which is not valid JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # 'nan', 'inf', '-inf'
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


# Thread-safe global registries for connection sharing
_connections: dict[str, duckdb.DuckDBPyConnection] = {}
_connection_read_only: dict[str, bool] = {}
_connection_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()

_MEMORY_LIMIT_RE = re.compile(r"[0-9]+(\.[0-9]+)?\s*(B|KB|MB|GB|TB|KIB|MIB|GIB|TIB)?", re.I)


def get_connection_and_lock(
    db_path: str, read_only: bool, reuse_any_mode: bool = False
) -> tuple[duckdb.DuckDBPyConnection, threading.Lock]:
    """Retrieve or initialize a cached database connection and its corresponding access lock.

    With ``reuse_any_mode`` a cached connection is returned whatever its mode
    (callers that only read work fine on either), so read tools don't force a
    close/reopen cycle that would drop session state (temp tables, extensions).
    """
    # Force read-write for in-memory databases because read-only :memory: is not supported.
    if db_path == ":memory:":
        read_only = False

    with _registry_lock:
        if db_path in _connections:
            if reuse_any_mode:
                return _connections[db_path], _connection_locks[db_path]
            existing_readonly = _connection_read_only.get(db_path, True)
            if existing_readonly != read_only:
                # Swap modes under the per-database lock so a query in flight
                # on the old connection is never closed mid-execution.
                conn = _connections.pop(db_path)
                _connection_read_only.pop(db_path, None)
                with _connection_locks[db_path]:
                    conn.close()

        if db_path not in _connections:
            conn = duckdb.connect(database=db_path, read_only=read_only)

            # Apply initial configuration parameters
            mem_limit = os.getenv("MCP_DUCKDB_MEMORY_LIMIT", "2GB")
            if not _MEMORY_LIMIT_RE.fullmatch(mem_limit.strip()):
                mem_limit = "2GB"
            conn.execute(f"SET max_memory = '{mem_limit}'")
            if os.getenv("MCP_DUCKDB_DISABLE_EXTERNAL_ACCESS", "false").lower() == "true":
                conn.execute("SET enable_external_access = false")

            _connections[db_path] = conn
            _connection_read_only[db_path] = read_only
            if db_path not in _connection_locks:
                _connection_locks[db_path] = threading.Lock()

        return _connections[db_path], _connection_locks[db_path]


@contextmanager
def connection_for(
    db_path: str, read_only: bool, reuse_any_mode: bool = False
) -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield the current connection for ``db_path`` while holding its lock.

    Re-checks identity after acquiring the lock: a concurrent mode swap may
    have closed the connection between the registry lookup and the lock
    acquisition. While the lock is held here, a swap cannot close it. Bounded
    retries; the last attempt proceeds regardless so this can never spin.
    """
    for attempt in range(3):
        conn, lock = get_connection_and_lock(db_path, read_only, reuse_any_mode)
        with lock:
            if attempt == 2 or _connections.get(db_path) is conn:
                yield conn
                return
            # Swapped under us before we got the lock; look it up again.


def format_db_error(e: Exception) -> str:
    """Format exceptions into helpful suggestions for the agent."""
    err_msg = str(e)
    suggestion = None

    if "Table with name" in err_msg or "does not exist" in err_msg:
        suggestion = "The table or view does not exist. Use the duckdb_list_tables tool to view available tables."
    elif "No files found" in err_msg or "cannot open file" in err_msg:
        suggestion = "Verify that the file path is correct and that the file exists."
    elif "Parser Error" in err_msg or "syntax error" in err_msg.lower():
        suggestion = "Check SQL query syntax. Note that SQL string literals must use single quotes (e.g. 'value'), not double quotes."

    output = {"error": err_msg}
    if suggestion:
        output["suggestion"] = suggestion
    return json.dumps(output)


def _max_chars() -> int:
    try:
        return int(os.getenv("MCP_DATA_MAX_CHARS", str(DEFAULT_MAX_CHARS)))
    except ValueError:
        return DEFAULT_MAX_CHARS


def _execute_query(args: DuckDbQueryArgs) -> str:
    db_path = args.database or ":memory:"

    try:
        with connection_for(db_path, args.read_only) as conn:
            cursor = conn.execute(args.query)
            if cursor.description is None:
                return json.dumps({"results": []})

            cols = [desc[0] for desc in cursor.description]

            # Fetch up to max_rows + 1 to detect truncation
            rows = cursor.fetchmany(args.max_rows + 1)
            truncated = len(rows) > args.max_rows
            if truncated:
                rows = rows[: args.max_rows]

        results = [_json_safe(dict(zip(cols, row, strict=True))) for row in rows]
        output: dict[str, Any] = {"results": results}
        if truncated:
            output["truncated"] = True
            output["warning"] = (
                f"Results truncated to {args.max_rows} rows to prevent context window overflow."
            )
        payload = json.dumps(output, cls=DuckDbJSONEncoder)

        # Char budget: max_rows alone cannot protect the context window.
        max_chars = _max_chars()
        while len(payload) > max_chars and len(results) > 1:
            results = results[: len(results) // 2]
            output = {
                "results": results,
                "truncated": True,
                "warning": (
                    f"Output exceeded the {max_chars}-char budget (MCP_DATA_MAX_CHARS); "
                    f"returning the first {len(results)} rows. Narrow the SELECT or "
                    f"aggregate to see more."
                ),
            }
            payload = json.dumps(output, cls=DuckDbJSONEncoder)
        if len(payload) > max_chars:
            return json.dumps(
                {
                    "error": (
                        f"A single result row exceeds the {max_chars}-char output "
                        f"budget (MCP_DATA_MAX_CHARS)."
                    ),
                    "suggestion": (
                        "Select fewer or narrower columns, or aggregate "
                        "(e.g. count/length) instead of returning raw values."
                    ),
                }
            )
        return payload
    except Exception as e:
        return format_db_error(e)


def _execute_close(args: DuckDbCloseDatabaseArgs) -> str:
    db_path = args.database or ":memory:"
    closed_keys = []

    with _registry_lock:
        if db_path in _connections:
            conn = _connections.pop(db_path)
            _connection_read_only.pop(db_path, None)
            lock = _connection_locks.pop(db_path)
            with lock:
                conn.close()
            closed_keys.append(db_path)

    if closed_keys:
        return json.dumps(
            {"status": "success", "message": f"Closed connections for: {', '.join(closed_keys)}"}
        )
    return json.dumps(
        {"status": "success", "message": "No active connections found for this database."}
    )


async def duckdb_query(args: DuckDbQueryArgs) -> str:
    """Run SQL over large local data files or scratch tables without reading them into context.

    Queries CSV/JSON/JSONL/Parquet files in place (e.g. SELECT level, count(*)
    FROM 'app.jsonl' GROUP BY 1) and returns only the answer rows. Tables built
    here persist across tool calls, so intermediate results can be stashed
    instead of re-derived. DuckDB SQL dialect.

    Args:
        query: The SQL query to run.
        database: Optional path to a persistent DuckDB file.
        read_only: Connect to the database in read-only mode (default False).
        max_rows: Max rows to return (default 2000). Output is also capped at
            MCP_DATA_MAX_CHARS characters (default 100000).
    """
    return await asyncio.to_thread(_execute_query, args)


async def duckdb_close_database(args: DuckDbCloseDatabaseArgs) -> str:
    """Close and release connection(s) to a database.

    Args:
        database: Optional path to a persistent DuckDB file. If omitted, closes the in-memory database.
    """
    return await asyncio.to_thread(_execute_close, args)
