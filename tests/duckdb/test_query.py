import json

import pytest

from mcp_servers.duckdb.models.schemas import (
    DuckDbCloseDatabaseArgs,
    DuckDbDescribeArgs,
    DuckDbListTablesArgs,
    DuckDbQueryArgs,
)
from mcp_servers.duckdb.tools.query import duckdb_close_database, duckdb_query
from mcp_servers.duckdb.tools.schema import duckdb_describe, duckdb_list_tables


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
    from mcp_servers.duckdb.tools.query import DuckDbJSONEncoder

    encoder = DuckDbJSONEncoder()
    with pytest.raises(TypeError):
        encoder.encode(object())


@pytest.mark.asyncio
async def test_cursor_description_none(mocker):
    # Mock connection execution to return a cursor with description = None
    from mcp_servers.duckdb.tools import query

    mock_cursor = mocker.MagicMock()
    mock_cursor.description = None

    mock_conn = mocker.MagicMock()
    mock_conn.execute.return_value = mock_cursor

    mocker.patch(
        "mcp_servers.duckdb.tools.query.get_connection_and_lock",
        return_value=(mock_conn, mocker.MagicMock()),
    )

    res = json.loads(await duckdb_query(DuckDbQueryArgs(query="CREATE TABLE foo")))
    assert res == {"results": []}

    # Reload original tool configuration
    import importlib

    importlib.reload(query)


@pytest.mark.asyncio
async def test_access_mode_exception(mocker, tmp_path):
    # Test get_connection_and_lock when connection access mode query raises Exception
    # This will cover line 52-53 in query.py
    from mcp_servers.duckdb.tools import query

    db_file = str(tmp_path / "dummy_db")
    mock_conn = mocker.MagicMock()
    mock_conn.execute.side_effect = Exception("mock error")

    query._connections[db_file] = mock_conn

    # We call get_connection_and_lock. If it fails querying access_mode,
    # it catches it and sets is_existing_readonly = True, then closes it.
    conn, lock = query.get_connection_and_lock(db_file, read_only=False)
    assert mock_conn.close.called

    # Clean registry
    query._connections.clear()
