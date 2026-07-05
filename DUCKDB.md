# Design Document: `mcp-duckdb` Server

This document outlines the design and implementation plan for the `mcp-duckdb` server, a new Python-based MCP server in this monorepo. It exposes DuckDB's analytical and relational SQL capabilities to AI agents, allowing them to dynamically create, manipulate, and query local databases and files (CSV, JSON, Parquet).

---

## 1. Overview & Use Cases

AI agents will use this server to dynamically create, load, manipulate, and analyze local databases and files:
1. **Dynamic Database Creation**: Build temporary or persistent databases on the fly (e.g., storing intermediate scrape results, parsed log files, or workspace metadata).
2. **Agent Memory & Experience Logging**: Store key-value states, execution history, or semantic/vector memories directly inside local database files.
3. **Log Analysis**: Query large JSONL/CSV log files directly without loading them entirely into the context (e.g., `SELECT error, count(*) FROM 'app.log' GROUP BY 1`).
4. **Data Transformations**: Load raw CSV/JSON files, run transformations/aggregations via SQL, and export the clean results.
5. **Schema & State Discovery**: Inspect tables, column types, and database metadata dynamically.
6. **SQLite Integration**: Query or import existing SQLite database files directly by utilizing DuckDB's native `sqlite` extension (`ATTACH 'file.db' AS sqlite (TYPE SQLITE)`).
7. **Federated Multi-Format Queries**: Join configurations (JSON), database state (SQLite), and system telemetry (CSV) in a single SQL statement.
8. **Data Regression Testing (Diffs)**: Assert dataset consistency across versions, branches, or commits using SQL operators like `EXCEPT` or `INTERSECT` to compare baselines.
9. **Time-Series Log Analytics**: Apply window functions (`LAG`, `LEAD`, etc.) to parse high-frequency application metrics.
10. **Codebase Analytics**: Query repository churn rates, commit metrics, and file complexity metrics.

---

## 2. Directory Layout

The new server follows the modular structure of the existing servers in `src/mcp_servers/`:

```
src/mcp_servers/
└── duckdb/
    ├── __init__.py
    ├── server.py              # FastMCP server instantiation and tool registration
    ├── models/
    │   ├── __init__.py
    │   └── schemas.py         # Pydantic schemas for input validation and path normalization
    └── tools/
        ├── __init__.py
        ├── query.py           # SQL query execution with error formatting
        └── schema.py          # Schema inspection and table listing tools
tests/
└── duckdb/
    ├── __init__.py
    ├── test_server.py
    └── test_query.py
```

---

## 3. Configuration & Integration

### `pyproject.toml`
Add `duckdb` to the project's dependencies and expose the console script:

```toml
[project]
dependencies = [
    ...
    "duckdb>=1.1.0",
]

[project.scripts]
mcp-github = "mcp_servers.github.server:main"
mcp-workspace = "mcp_servers.workspace.server:main"
mcp-duckdb = "mcp_servers.duckdb.server:main"
```

---

## 4. Input Schemas (`models/schemas.py`)

Using Pydantic v2 to ensure strict validation of inputs. Paths are normalized and expanded automatically using Pydantic field validators:

```python
from __future__ import annotations

import os
from pydantic import BaseModel, Field, field_validator

def normalize_path(v: str | None) -> str | None:
    if v is None:
        return None
    return os.path.abspath(os.path.expanduser(v))

class DuckDbQueryArgs(BaseModel, frozen=True):
    query: str = Field(
        ...,
        description="The SQL query to run. Supports both read queries (SELECT) and mutations (CREATE, INSERT, UPDATE, DROP, COPY)."
    )
    database: str | None = Field(
        None,
        description="Path to a persistent DuckDB database file (e.g., 'data.db'). If omitted, runs against a temporary in-memory database."
    )
    read_only: bool = Field(
        False,
        description="Connect to the database in read-only mode. Defaults to False to allow mutations."
    )
    max_rows: int = Field(
        2000,
        ge=1,
        le=10000,
        description="Max rows to return to prevent context window overflow. Defaults to 2000."
    )

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)

class DuckDbDescribeArgs(BaseModel, frozen=True):
    path: str = Field(
        ...,
        description="Path to a CSV, JSON, Parquet file, or table/view name to describe."
    )
    database: str | None = Field(
        None,
        description="Path to a persistent DuckDB database file (optional)."
    )

    @field_validator("path")
    @classmethod
    def validate_target_path(cls, v: str) -> str:
        # Resolve target path if it looks like a file (extensions or path separators)
        if "/" in v or "\\" in v or any(v.endswith(ext) for ext in [".csv", ".tsv", ".json", ".jsonl", ".parquet"]):
            resolved = normalize_path(v)
            return resolved if resolved is not None else v
        return v

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)

class DuckDbListTablesArgs(BaseModel, frozen=True):
    database: str | None = Field(
        None,
        description="Path to a persistent DuckDB database file (optional)."
    )

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)

class DuckDbCloseDatabaseArgs(BaseModel, frozen=True):
    database: str | None = Field(
        None,
        description="Path to the database connection to close (e.g. 'data.db' or omit for in-memory)."
    )

    @field_validator("database")
    @classmethod
    def validate_database_path(cls, v: str | None) -> str | None:
        return normalize_path(v)
```

---

## 5. Tool Implementations (`tools/`)

To prevent blocking the main asyncio event loop, all database transactions run inside worker threads via `asyncio.to_thread`. Standard exceptions are caught and augmented with helpful troubleshooting suggestions.

A global connection registry maintains active connections (particularly essential for `:memory:` state and loaded extensions) and uses fine-grained locks to serialize concurrent calls on the same connection.

### `tools/query.py`

```python
from __future__ import annotations

import asyncio
import decimal
import json
import os
import threading
from datetime import date, datetime
import duckdb
from ..models.schemas import DuckDbQueryArgs, DuckDbCloseDatabaseArgs

class DuckDbJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to safely serialize dates, decimals, and bytes."""
    def default(self, obj):
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        return super().default(obj)

# Thread-safe global registries for connection sharing
_connections: dict[str, duckdb.DuckDBPyConnection] = {}
_connection_locks: dict[str, threading.Lock] = {}
_registry_lock = threading.Lock()

def get_connection_and_lock(db_path: str, read_only: bool) -> tuple[duckdb.DuckDBPyConnection, threading.Lock]:
    """Retrieve or initialize a cached database connection and its corresponding access lock."""
    cache_key = f"{db_path}:{read_only}"
    with _registry_lock:
        if cache_key not in _connections:
            conn = duckdb.connect(database=db_path, read_only=read_only)

            # Apply initial configuration parameters
            mem_limit = os.getenv("MCP_DUCKDB_MEMORY_LIMIT", "2GB")
            conn.execute(f"SET max_memory = '{mem_limit}'")
            if os.getenv("MCP_DUCKDB_DISABLE_EXTERNAL_ACCESS", "false").lower() == "true":
                conn.execute("SET disable_external_access = true")

            _connections[cache_key] = conn
            _connection_locks[cache_key] = threading.Lock()

        return _connections[cache_key], _connection_locks[cache_key]

def format_db_error(e: Exception) -> str:
    """Format exceptions into helpful suggestions for the agent."""
    err_msg = str(e)
    suggestion = None

    if "Table with name" in err_msg or "does not exist" in err_msg:
        suggestion = "The table or view does not exist. Use the duckdb_list_tables tool to view available tables."
    elif "No files found matching" in err_msg or "cannot open file" in err_msg:
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
                # Mutation query (e.g., CREATE TABLE, INSERT, COPY)
                return json.dumps({"status": "success", "rows_affected": conn.changes()})

            cols = [desc[0] for desc in cursor.description]

            # Fetch up to max_rows + 1 to detect truncation
            rows = cursor.fetchmany(args.max_rows + 1)
            truncated = len(rows) > args.max_rows
            if truncated:
                rows = rows[:args.max_rows]

            results = [dict(zip(cols, row)) for row in rows]
            output = {"results": results}
            if truncated:
                output["truncated"] = True
                output["warning"] = f"Results truncated to {args.max_rows} rows to prevent context window overflow."

            return json.dumps(output, cls=DuckDbJSONEncoder)
    except Exception as e:
        return format_db_error(e)

def _execute_close(args: DuckDbCloseDatabaseArgs) -> str:
    db_path = args.database or ":memory:"
    closed_keys = []

    with _registry_lock:
        # Close matching active connections (both read-write and read-only)
        keys_to_close = [k for k in _connections if k.startswith(f"{db_path}:")]
        for key in keys_to_close:
            conn = _connections.pop(key)
            lock = _connection_locks.pop(key, None)
            if lock:
                with lock:
                    conn.close()
            else:
                conn.close()
            closed_keys.append(key)

    if closed_keys:
        return json.dumps({"status": "success", "message": f"Closed connection keys: {', '.join(closed_keys)}"})
    return json.dumps({"status": "success", "message": "No active connections found for this database."})

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
```

### `tools/schema.py`

```python
from __future__ import annotations

import asyncio
import json
from ..models.schemas import DuckDbDescribeArgs, DuckDbListTablesArgs
from .query import DuckDbJSONEncoder, format_db_error, get_connection_and_lock

def _execute_describe(args: DuckDbDescribeArgs) -> str:
    db_path = args.database or ":memory:"
    target = args.path

    if any(target.endswith(ext) for ext in [".csv", ".tsv", ".json", ".jsonl", ".parquet"]):
        query = f"DESCRIBE SELECT * FROM '{target}' LIMIT 0"
    else:
        query = f"DESCRIBE {target}"

    try:
        conn, lock = get_connection_and_lock(db_path, read_only=True)
        with lock:
            cursor = conn.execute(query)
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            results = [dict(zip(cols, row)) for row in rows]
            return json.dumps({"schema": results}, cls=DuckDbJSONEncoder)
    except Exception as e:
        return format_db_error(e)

def _execute_list_tables(args: DuckDbListTablesArgs) -> str:
    db_path = args.database or ":memory:"

    try:
        conn, lock = get_connection_and_lock(db_path, read_only=True)
        with lock:
            cursor = conn.execute("SHOW TABLES")
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            results = [row[0] for row in rows]
            return json.dumps({"tables": results})
    except Exception as e:
        return format_db_error(e)

async def duckdb_describe(args: DuckDbDescribeArgs) -> str:
    """Get the schema (columns, types, nullability) of a file or table.

    Args:
        path: Path to the target file (CSV, JSON, Parquet) or table name.
        database: Optional path to a persistent DuckDB file.
    """
    return await asyncio.to_thread(_execute_describe, args)

async def duckdb_list_tables(args: DuckDbListTablesArgs) -> str:
    """List all tables and views in the database.

    Args:
        database: Optional path to a persistent DuckDB file.
    """
    return await asyncio.to_thread(_execute_list_tables, args)
```

---

## 6. Server Entry Point (`server.py`)

```python
"""DuckDB MCP Server.

Provides SQL query execution, schema description, and table discovery.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from . import tools

mcp = FastMCP("duckdb")

# Register tools
mcp.tool()(tools.duckdb_query)
mcp.tool()(tools.duckdb_describe)
mcp.tool()(tools.duckdb_list_tables)
mcp.tool()(tools.duckdb_close_database)

def main() -> None:
    """Console-script entry point."""
    mcp.run()

if __name__ == "__main__":
    main()
```

---

## 7. Production Readiness Checklist

### Security
* [x] **Local Path Traversal Rules**: Verify that file imports respect the same workspace constraints as the rest of the ecosystem.
* [x] **Resource Limits**: Ensure `max_memory` limits are set by default to prevent query tasks from causing system Out-Of-Memory events.
* [x] **External Network Controls**: Verify `enable_external_access = false` blocks remote files if `MCP_DUCKDB_DISABLE_EXTERNAL_ACCESS=true`.

### Code Quality & Stability
* [x] **Async Loop Safety**: Ensure no synchronous DuckDB calls run directly in the event loop thread; they must use `asyncio.to_thread`.
* [x] **Encoder Reliability**: Run query tests that select dates, times, decimals, and blobs to confirm `DuckDbJSONEncoder` serializes them without error.
* [x] **Session State & Caching**: Verify connection cache registry successfully retains `:memory:` states and loaded extensions across separate tool calls.
* [x] Run `ruff check .` and `ruff format .` to verify formatting.
* [x] Run `ty check` to ensure type checks pass.

### Test Strategy (`tests/duckdb/`)
* [x] `test_query_memory`: Run basic read queries against `:memory:`.
* [x] `test_query_write`: Run write queries (`CREATE TABLE`, `INSERT`) and verify changes persist across queries on the same connection/file.
* [x] `test_query_read_only`: Verify `read_only=True` prevents modifications to tables.
* [x] `test_list_tables`: Create multiple tables and verify `duckdb_list_tables` lists them correctly.
* [x] `test_describe`: Verify schema description works for both tables and direct file queries.
* [x] `test_truncation`: Verify queries returning large rows truncate gracefully at `max_rows` and attach the truncation warning.
* [x] `test_json_encoder`: Run queries returning dates/decimals and assert successful string outputs.
* [x] `test_connection_caching`: Assert that creating a table in `:memory:` in one tool call makes it queries-able in a subsequent tool call.
* [x] `test_close_database`: Verify closing a connection successfully releases files and removes them from the registry cache.

---

## 8. Agent Memory Storage Examples

When an agent needs to persist its state, context, or experiences, it can execute standard DDL/DML statements against a persistent database.

### Key-Value State / Document Store
```sql
CREATE TABLE IF NOT EXISTS agent_state (
    key VARCHAR PRIMARY KEY,
    value JSON,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Storing value
INSERT OR REPLACE INTO agent_state (key, value)
VALUES ('user_preferences', '{"theme": "dark", "preferred_editor": "vscode"}');
```

### Semantic Memory (Vector Search)
Using DuckDB's `vss` extension for embeddings-based memory:
```sql
INSTALL vss;
LOAD vss;

CREATE TABLE IF NOT EXISTS semantic_memory (
    id VARCHAR PRIMARY KEY DEFAULT uuid(),
    content TEXT,
    embedding FLOAT[1536],
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Semantic search (Cosine similarity or HNSW)
-- SELECT content FROM semantic_memory ORDER BY array_cosine_distance(embedding, ?) LIMIT 5;
```
