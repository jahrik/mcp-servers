from __future__ import annotations

import json
from datetime import UTC

import pytest

from mcp_servers.data.models.schemas import (
    DuckDbCloseDatabaseArgs,
    DuckDbDescribeArgs,
    DuckDbListTablesArgs,
    DuckDbQueryArgs,
)
from mcp_servers.data.tools.query import duckdb_close_database, duckdb_query
from mcp_servers.data.tools.schema import duckdb_describe, duckdb_list_tables


@pytest.mark.asyncio
async def test_query_memory():
    args = DuckDbQueryArgs(query="SELECT 42 as answer", database=None)
    res = json.loads(await duckdb_query(args))
    assert res["results"] == [{"answer": 42}]


@pytest.mark.asyncio
async def test_query_write():
    # Create table and insert a row
    args1 = DuckDbQueryArgs(query="CREATE TABLE users (id INTEGER, name VARCHAR)")
    res1 = json.loads(await duckdb_query(args1))
    assert "error" not in res1

    args2 = DuckDbQueryArgs(query="INSERT INTO users VALUES (1, 'Alice')")
    res2 = json.loads(await duckdb_query(args2))
    assert "error" not in res2

    args3 = DuckDbQueryArgs(query="SELECT * FROM users")
    res3 = json.loads(await duckdb_query(args3))
    assert res3["results"] == [{"id": 1, "name": "Alice"}]

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_query_read_only(tmp_path):
    # Connect in read-only mode to check if write fails on a file database
    # (Since read-only in-memory is not supported by DuckDB and gets forced to read-write)
    db_file = tmp_path / "test_ro.db"

    # Initialize DB file first
    args_init = DuckDbQueryArgs(database=str(db_file), query="CREATE TABLE ro_users (id INT)")
    await duckdb_query(args_init)
    await duckdb_close_database(DuckDbCloseDatabaseArgs(database=str(db_file)))

    args = DuckDbQueryArgs(
        database=str(db_file), query="INSERT INTO ro_users VALUES (1)", read_only=True
    )
    res = json.loads(await duckdb_query(args))
    assert "error" in res
    assert "read-only" in res["error"].lower()

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs(database=str(db_file)))


@pytest.mark.asyncio
async def test_list_tables():
    # Make sure we clean connection cache first
    await duckdb_close_database(DuckDbCloseDatabaseArgs())

    # Create tables
    await duckdb_query(DuckDbQueryArgs(query="CREATE TABLE t1 (x INT)"))
    await duckdb_query(DuckDbQueryArgs(query="CREATE TABLE t2 (y INT)"))

    res = json.loads(await duckdb_list_tables(DuckDbListTablesArgs()))
    assert "t1" in res["tables"]
    assert "t2" in res["tables"]

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_list_tables_sees_all_schemas():
    # SHOW TABLES only covers main; tables in other schemas must be listed
    # too, schema-qualified.
    await duckdb_close_database(DuckDbCloseDatabaseArgs())
    await duckdb_query(
        DuckDbQueryArgs(query="CREATE SCHEMA stats; CREATE TABLE stats.runs (x INT)")
    )

    res = json.loads(await duckdb_list_tables(DuckDbListTablesArgs()))
    assert "stats.runs" in res["tables"]

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_describe(tmp_path):
    # Make sure connection cache is clean
    await duckdb_close_database(DuckDbCloseDatabaseArgs())

    db_file = tmp_path / "test_desc.db"
    await duckdb_query(
        DuckDbQueryArgs(query="CREATE TABLE test_desc (a INT, b VARCHAR)", database=str(db_file))
    )

    # Test table describe (with explicit database path)
    res1 = json.loads(
        await duckdb_describe(DuckDbDescribeArgs(path="test_desc", database=str(db_file)))
    )
    assert any(
        col["column_name"] == "a" and col["column_type"] == "INTEGER" for col in res1["schema"]
    )
    assert any(
        col["column_name"] == "b" and col["column_type"] == "VARCHAR" for col in res1["schema"]
    )

    # Test CSV file describe
    csv_file = tmp_path / "data.csv"
    csv_file.write_text("id,val\n1,hello\n2,world\n")
    res2 = json.loads(await duckdb_describe(DuckDbDescribeArgs(path=str(csv_file))))
    assert any(
        col["column_name"] == "id" and col["column_type"] == "BIGINT" for col in res2["schema"]
    )
    assert any(
        col["column_name"] == "val" and col["column_type"] == "VARCHAR" for col in res2["schema"]
    )

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_truncation():
    # Generate 10 rows and truncate to 5
    args = DuckDbQueryArgs(query="SELECT * FROM range(10) t(x)", max_rows=5)
    res = json.loads(await duckdb_query(args))
    assert len(res["results"]) == 5
    assert res["truncated"] is True
    assert "warning" in res


@pytest.mark.asyncio
async def test_json_encoder():
    args = DuckDbQueryArgs(query="SELECT DATE '2026-07-05' as d, DECIMAL '123.45' as dec")
    res = json.loads(await duckdb_query(args))
    assert res["results"] == [{"d": "2026-07-05", "dec": 123.45}]


@pytest.mark.asyncio
async def test_connection_caching():
    # Make sure we start with a clean connection
    await duckdb_close_database(DuckDbCloseDatabaseArgs())

    # Create table in one query
    args1 = DuckDbQueryArgs(query="CREATE TABLE cache_test (x INT)")
    await duckdb_query(args1)

    # Insert in another query (reusing the cached connection)
    args2 = DuckDbQueryArgs(query="INSERT INTO cache_test VALUES (100)")
    await duckdb_query(args2)

    # Select in a third query
    args3 = DuckDbQueryArgs(query="SELECT * FROM cache_test")
    res = json.loads(await duckdb_query(args3))
    assert res["results"] == [{"x": 100}]

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_close_database():
    # Create table and insert a row
    args1 = DuckDbQueryArgs(query="CREATE TABLE close_test (x INT)")
    await duckdb_query(args1)

    # Close the database
    res_close = json.loads(await duckdb_close_database(DuckDbCloseDatabaseArgs()))
    assert res_close["status"] == "success"

    # Querying again will start a fresh in-memory db, so table close_test will not exist
    args2 = DuckDbQueryArgs(query="SELECT * FROM close_test")
    res2 = json.loads(await duckdb_query(args2))
    assert "error" in res2
    assert "does not exist" in res2["error"]


@pytest.mark.asyncio
async def test_path_normalization_and_expansion():
    # Test path normalization by querying with a relative path
    args = DuckDbListTablesArgs(database="~/test_expand.db")
    # This validator will expand '~' to home directory
    assert args.database is not None
    assert args.database.startswith("/")


@pytest.mark.asyncio
async def test_describe_missing_and_error(tmp_path):
    # Trigger exception in _execute_describe by describing a non-existent table/file
    res = json.loads(await duckdb_describe(DuckDbDescribeArgs(path="nonexistent_table_name")))
    assert "error" in res
    assert "does not exist" in res["error"]


@pytest.mark.asyncio
async def test_list_tables_error():
    # Trigger exception in list_tables by passing a directory path as database file
    res = json.loads(
        await duckdb_list_tables(DuckDbListTablesArgs(database="/invalid/path/dir.db"))
    )
    assert "error" in res


@pytest.mark.asyncio
async def test_parser_error():
    args = DuckDbQueryArgs(query="SELECT FROM")
    res = json.loads(await duckdb_query(args))
    assert "error" in res
    assert "suggestion" in res
    assert "Check SQL query syntax" in res["suggestion"]


@pytest.mark.asyncio
async def test_file_not_found_error():
    args = DuckDbQueryArgs(query="SELECT * FROM 'nonexistent_file_xyz.csv'")
    res = json.loads(await duckdb_query(args))
    assert "error" in res
    assert "suggestion" in res
    assert "Verify that the file path is correct" in res["suggestion"]


@pytest.mark.asyncio
async def test_disable_external_access(monkeypatch):
    monkeypatch.setenv("MCP_DUCKDB_DISABLE_EXTERNAL_ACCESS", "true")
    # Clean connection first
    await duckdb_close_database(DuckDbCloseDatabaseArgs())
    # Query something basic
    args = DuckDbQueryArgs(query="SELECT 1")
    res = json.loads(await duckdb_query(args))
    assert "error" not in res
    # Clean up again to reset env var effects
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_bytes_serialization():
    args = DuckDbQueryArgs(query="SELECT CAST('hello' AS BLOB) as b")
    res = json.loads(await duckdb_query(args))
    assert res["results"] == [{"b": "hello"}]


def test_json_encoder_fallback():
    # Unknown types are stringified, never a serialization error.
    from mcp_servers.data.tools.query import DuckDbJSONEncoder

    encoder = DuckDbJSONEncoder()
    assert json.loads(encoder.encode(object())).startswith("<object object at")


@pytest.mark.asyncio
async def test_rich_type_serialization():
    # UUID, INTERVAL, TIME, and TIMESTAMPTZ show up constantly in real data
    # (read_json auto-types UUID-shaped strings) and must serialize cleanly.
    res = json.loads(
        await duckdb_query(
            DuckDbQueryArgs(
                query="SELECT uuid() AS u, INTERVAL '3 days' AS iv, TIME '12:34:56' AS t, "
                "TIMESTAMPTZ '2026-01-01 00:00:00+00' AS ts"
            )
        )
    )
    assert "error" not in res
    row = res["results"][0]
    assert len(row["u"]) == 36
    assert "day" in row["iv"]
    assert row["t"] == "12:34:56"
    # TIMESTAMPTZ renders in the session timezone; compare the instant.
    from datetime import datetime

    assert datetime.fromisoformat(row["ts"]) == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.asyncio
async def test_nonfinite_floats_are_valid_json():
    # json.dumps emits bare NaN/Infinity by default, which strict JSON
    # parsers reject; non-finite floats must come back as strings.
    out = await duckdb_query(
        DuckDbQueryArgs(query="SELECT 'nan'::FLOAT AS a, 'inf'::FLOAT AS b, '-inf'::FLOAT AS c")
    )

    def reject_constant(c):
        raise ValueError(f"non-strict JSON constant {c}")

    res = json.loads(out, parse_constant=reject_constant)
    assert res["results"] == [{"a": "nan", "b": "inf", "c": "-inf"}]


@pytest.mark.asyncio
async def test_char_budget_truncates_rows(monkeypatch):
    monkeypatch.setenv("MCP_DATA_MAX_CHARS", "2000")
    res = json.loads(
        await duckdb_query(
            DuckDbQueryArgs(query="SELECT range AS i, repeat('x', 100) AS pad FROM range(500)")
        )
    )
    assert res["truncated"] is True
    assert "MCP_DATA_MAX_CHARS" in res["warning"]
    assert 0 < len(res["results"]) < 500


@pytest.mark.asyncio
async def test_nonfinite_floats_inside_lists():
    res = json.loads(
        await duckdb_query(DuckDbQueryArgs(query="SELECT [1.0, 'nan'::FLOAT] AS pair"))
    )
    assert res["results"] == [{"pair": [1.0, "nan"]}]


@pytest.mark.asyncio
async def test_invalid_memory_limit_falls_back(monkeypatch):
    # A non-size value must not be interpolated into SET max_memory.
    monkeypatch.setenv("MCP_DUCKDB_MEMORY_LIMIT", "2GB'; DROP TABLE x; --")
    await duckdb_close_database(DuckDbCloseDatabaseArgs())
    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="SELECT 1 AS ok")))
    assert res["results"] == [{"ok": 1}]
    await duckdb_close_database(DuckDbCloseDatabaseArgs())


@pytest.mark.asyncio
async def test_invalid_max_chars_falls_back(monkeypatch):
    monkeypatch.setenv("MCP_DATA_MAX_CHARS", "not-a-number")
    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="SELECT 1 AS ok")))
    assert res["results"] == [{"ok": 1}]


@pytest.mark.asyncio
async def test_query_timeout_interrupts_runaway_sql(monkeypatch):
    monkeypatch.setenv("MCP_DATA_QUERY_TIMEOUT", "0.2")
    res = json.loads(
        await duckdb_query(
            DuckDbQueryArgs(query="SELECT count(*) FROM range(100000000) a, range(1000) b")
        )
    )
    assert "error" in res
    assert "timeout" in res["error"]
    assert "MCP_DATA_QUERY_TIMEOUT" in res["suggestion"]


@pytest.mark.asyncio
async def test_query_timeout_disabled_and_invalid(monkeypatch):
    monkeypatch.setenv("MCP_DATA_QUERY_TIMEOUT", "0")
    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="SELECT 1 AS ok")))
    assert res["results"] == [{"ok": 1}]

    monkeypatch.setenv("MCP_DATA_QUERY_TIMEOUT", "not-a-number")
    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="SELECT 2 AS ok")))
    assert res["results"] == [{"ok": 2}]


@pytest.mark.asyncio
async def test_char_budget_single_giant_row(monkeypatch):
    monkeypatch.setenv("MCP_DATA_MAX_CHARS", "2000")
    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="SELECT repeat('x', 5000) AS big")))
    assert "error" in res
    assert "budget" in res["error"]
    assert "suggestion" in res


@pytest.mark.asyncio
async def test_cursor_description_none(mocker):
    # Mock connection execution to return a cursor with description = None
    from mcp_servers.data.tools import query

    mock_cursor = mocker.MagicMock()
    mock_cursor.description = None

    mock_conn = mocker.MagicMock()
    mock_conn.execute.return_value = mock_cursor

    mocker.patch(
        "mcp_servers.data.tools.query.get_connection_and_lock",
        return_value=(mock_conn, mocker.MagicMock()),
    )

    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="CREATE TABLE foo")))
    assert res == {"results": []}

    # Reload original tool configuration
    import importlib

    importlib.reload(query)


@pytest.mark.asyncio
async def test_read_only_bypass_with_cached_rw_connection(tmp_path):
    # Test that opening a persistent DB in RW mode, and then (without closing)
    # attempting a write with read_only=True fails.
    db_file = tmp_path / "ro_bypass.db"

    # 1. Open and create table in read-write (read_only=False) mode
    args1 = DuckDbQueryArgs(
        database=str(db_file), query="CREATE TABLE test_bypass (x INT)", read_only=False
    )
    res1 = json.loads(await duckdb_query(args1))
    assert "error" not in res1

    # 2. Run query with read_only=True to insert a row.
    # The cached read-write connection is swapped for a read-only one on the
    # mode mismatch, so the write must fail on the read-only connection.
    args2 = DuckDbQueryArgs(
        database=str(db_file), query="INSERT INTO test_bypass VALUES (42)", read_only=True
    )
    res2 = json.loads(await duckdb_query(args2))
    assert "error" in res2
    assert "read-only" in res2["error"].lower()

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs(database=str(db_file)))


@pytest.mark.asyncio
async def test_read_tools_reuse_cached_connection(tmp_path):
    # describe/list_tables must reuse the cached connection whatever its mode,
    # instead of closing and reopening it (which would drop session state).
    db_file = tmp_path / "reuse.db"

    res1 = json.loads(
        await duckdb_query(
            DuckDbQueryArgs(
                database=str(db_file),
                query="CREATE TEMP TABLE session_state (x INT)",
                read_only=False,
            )
        )
    )
    assert "error" not in res1

    # The temp table only exists on the original connection: describing it
    # proves the read-write connection was reused rather than swapped out.
    res2 = json.loads(
        await duckdb_describe(DuckDbDescribeArgs(path="session_state", database=str(db_file)))
    )
    assert "error" not in res2
    assert res2["schema"][0]["column_name"] == "x"

    res3 = json.loads(await duckdb_list_tables(DuckDbListTablesArgs(database=str(db_file))))
    assert "error" not in res3

    # Clean up
    await duckdb_close_database(DuckDbCloseDatabaseArgs(database=str(db_file)))


@pytest.mark.asyncio
async def test_describe_identifier_quoting(tmp_path):
    # Test that identifiers are correctly quoted in duckdb_describe
    db_file = tmp_path / "quoting.db"

    # Create schema and table to test dotted quoting
    await duckdb_query(DuckDbQueryArgs(query="CREATE SCHEMA my_schema", database=str(db_file)))
    await duckdb_query(
        DuckDbQueryArgs(query="CREATE TABLE my_schema.test_table (x INT)", database=str(db_file))
    )

    # Create table with double quote in name to test quote escaping
    await duckdb_query(
        DuckDbQueryArgs(query='CREATE TABLE "my""table" (y INT)', database=str(db_file))
    )

    # Describe dotted identifier (should succeed as "my_schema"."test_table")
    res1 = json.loads(
        await duckdb_describe(
            DuckDbDescribeArgs(path="my_schema.test_table", database=str(db_file))
        )
    )
    assert "schema" in res1
    assert res1["schema"][0]["column_name"] == "x"

    # Describe identifier with double quotes (should succeed as "my""table")
    res2 = json.loads(
        await duckdb_describe(DuckDbDescribeArgs(path='my"table', database=str(db_file)))
    )
    assert "schema" in res2
    assert res2["schema"][0]["column_name"] == "y"

    await duckdb_close_database(DuckDbCloseDatabaseArgs(database=str(db_file)))
