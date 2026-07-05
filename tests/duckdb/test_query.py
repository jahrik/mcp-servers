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
    args = DuckDbQueryArgs(query="SELECT 42 as answer")
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

    await duckdb_query(DuckDbQueryArgs(query="CREATE TABLE test_desc (a INT, b VARCHAR)"))

    # Test table describe
    res1 = json.loads(await duckdb_describe(DuckDbDescribeArgs(path="test_desc")))
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
