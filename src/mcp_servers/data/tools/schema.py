from __future__ import annotations

import asyncio
import json

from ..models.schemas import DuckDbDescribeArgs, DuckDbListTablesArgs
from .query import DuckDbJSONEncoder, connection_for, format_db_error


def quote_identifier(name: str) -> str:
    """Quote table/view identifiers with double quotes, escaping internal double quotes."""
    parts = name.split(".")
    quoted_parts = [f'"{part.replace('"', '""')}"' for part in parts]
    return ".".join(quoted_parts)


def _execute_describe(args: DuckDbDescribeArgs) -> str:
    db_path = args.database or ":memory:"
    target = args.path

    if any(target.endswith(ext) for ext in [".csv", ".tsv", ".json", ".jsonl", ".parquet"]):
        escaped_path = target.replace("'", "''")
        query = f"DESCRIBE SELECT * FROM '{escaped_path}' LIMIT 0"
    else:
        query = f"DESCRIBE {quote_identifier(target)}"

    try:
        with connection_for(db_path, read_only=True, reuse_any_mode=True) as conn:
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
        with connection_for(db_path, read_only=True, reuse_any_mode=True) as conn:
            # SHOW TABLES only covers the main schema; SHOW ALL TABLES sees
            # every schema and attached database.
            cursor = conn.execute("SHOW ALL TABLES")
            cols = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            results = []
            for row in rows:
                rec = dict(zip(cols, row, strict=True))
                name = rec["name"] if rec["schema"] == "main" else f"{rec['schema']}.{rec['name']}"
                results.append(name)
            return json.dumps({"tables": results})
    except Exception as e:
        return format_db_error(e)


async def duckdb_describe(args: DuckDbDescribeArgs) -> str:
    """Peek at the schema (columns, types) of a local data file or scratch table without reading it.

    Use before duckdb_query on an unfamiliar CSV/JSON/JSONL/Parquet file to
    learn its columns from a zero-row scan.

    Args:
        path: Path to the target file (CSV, JSON, Parquet) or table name.
        database: Optional path to a persistent DuckDB file.
    """
    return await asyncio.to_thread(_execute_describe, args)


async def duckdb_list_tables(args: DuckDbListTablesArgs) -> str:
    """List all tables and views across every schema in the database.

    Names outside the main schema come back schema-qualified (e.g. 'stats.runs').

    Args:
        database: Optional path to a persistent DuckDB file.
    """
    return await asyncio.to_thread(_execute_list_tables, args)
