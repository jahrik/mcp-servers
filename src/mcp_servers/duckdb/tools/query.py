from __future__ import annotations

import asyncio
import decimal
import json
import os
import threading
from datetime import date, datetime
from typing import Any

import duckdb

from ..models.schemas import DuckDbCloseDatabaseArgs, DuckDbQueryArgs


class DuckDbJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to safely serialize dates, decimals, and bytes."""

    def default(self, o: Any) -> Any:
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        if isinstance(o, decimal.Decimal):
            return float(o)
        if isinstance(o, bytes):
            return o.decode("utf-8", errors="replace")
        return super().default(o)


# Thread-safe global registries for connection sharing
_connections: dict[str, duckdb.DuckDBPyConnection] = {}
_connection_read_only: dict[str, bool] = {}
_connection_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()


def get_connection_and_lock(
    db_path: str, read_only: bool
) -> tuple[duckdb.DuckDBPyConnection, threading.Lock]:
    """Retrieve or initialize a cached database connection and its corresponding access lock."""
    # Force read-write for in-memory databases because read-only :memory: is not supported.
    if db_path == ":memory:":
        read_only = False

    with _registry_lock:
        if db_path in _connections:
            existing_readonly = _connection_read_only.get(db_path, True)
            if existing_readonly != read_only:
                conn = _connections.pop(db_path)
                conn.close()

        if db_path not in _connections:
            conn = duckdb.connect(database=db_path, read_only=read_only)

            # Apply initial configuration parameters
            mem_limit = os.getenv("MCP_DUCKDB_MEMORY_LIMIT", "2GB")
            conn.execute(f"SET max_memory = '{mem_limit}'")
            if os.getenv("MCP_DUCKDB_DISABLE_EXTERNAL_ACCESS", "false").lower() == "true":
                conn.execute("SET enable_external_access = false")

            _connections[db_path] = conn
            _connection_read_only[db_path] = read_only
            if db_path not in _connection_locks:
                _connection_locks[db_path] = threading.Lock()

        return _connections[db_path], _connection_locks[db_path]


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


def _execute_query(args: DuckDbQueryArgs) -> str:
    db_path = args.database or ":memory:"

    try:
        conn, lock = get_connection_and_lock(db_path, args.read_only)
        with lock:
            cursor = conn.execute(args.query)
            if cursor.description is None:
                return json.dumps({"results": []})

            cols = [desc[0] for desc in cursor.description]

            # Fetch up to max_rows + 1 to detect truncation
            rows = cursor.fetchmany(args.max_rows + 1)
            truncated = len(rows) > args.max_rows
            if truncated:
                rows = rows[: args.max_rows]

            results = [dict(zip(cols, row, strict=True)) for row in rows]
            output = {"results": results}
            if truncated:
                output["truncated"] = True
                output["warning"] = (
                    f"Results truncated to {args.max_rows} rows to prevent context window overflow."
                )

            return json.dumps(output, cls=DuckDbJSONEncoder)
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
    """Execute a SQL query against DuckDB (in-memory or persistent file).

    Args:
        query: The SQL query to run.
        database: Optional path to a persistent DuckDB file.
        read_only: Connect to the database in read-only mode (default False).
        max_rows: Max rows to return (default 2000).
    """
    return await asyncio.to_thread(_execute_query, args)


async def duckdb_close_database(args: DuckDbCloseDatabaseArgs) -> str:
    """Close and release connection(s) to a database.

    Args:
        database: Optional path to a persistent DuckDB file. If omitted, closes the in-memory database.
    """
    return await asyncio.to_thread(_execute_close, args)
