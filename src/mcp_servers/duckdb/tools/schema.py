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
            results = [dict(zip(cols, row, strict=True)) for row in rows]
            return json.dumps({"schema": results}, cls=DuckDbJSONEncoder)
    except Exception as e:
        return format_db_error(e)


def _execute_list_tables(args: DuckDbListTablesArgs) -> str:
    db_path = args.database or ":memory:"

    try:
        conn, lock = get_connection_and_lock(db_path, read_only=True)
        with lock:
            cursor = conn.execute("SHOW TABLES")
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
