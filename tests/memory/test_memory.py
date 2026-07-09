from __future__ import annotations

import json

import pytest

from mcp_servers.memory.models.schemas import (
    ForgetArgs,
    ListMemoriesArgs,
    RecallArgs,
    RememberArgs,
)
from mcp_servers.memory.server import main, mcp
from mcp_servers.memory.tools import db
from mcp_servers.memory.tools.forget import forget
from mcp_servers.memory.tools.list_memories import list_memories
from mcp_servers.memory.tools.recall import recall
from mcp_servers.memory.tools.remember import remember


@pytest.fixture(autouse=True)
def use_test_db(tmp_path, monkeypatch):
    """Override the database path to use a temp directory during testing."""
    test_db_path = str(tmp_path / "test_memory.db")
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    return test_db_path


def test_server_main(monkeypatch):
    """Verify that main runs and triggers the server start."""
    called = False

    def mock_run():
        nonlocal called
        called = True

    monkeypatch.setattr(mcp, "run", mock_run)
    main()
    assert called


@pytest.mark.asyncio
async def test_remember_and_list():
    """Test storing memories and listing them."""
    # Storing a new memory
    args = RememberArgs(
        content="Antigravity is a pair programming AI assistant.",
        key="assistant_info",
        category="general",
        tags=["ai", "pair-programming"],
    )
    res_str = await remember(args)
    res = json.loads(res_str)
    assert res["status"] == "success"
    assert res["action"] == "created"
    assert res["key"] == "assistant_info"

    # Listing memories
    list_args = ListMemoriesArgs(limit=10)
    list_res_str = await list_memories(list_args)
    list_res = json.loads(list_res_str)
    memories = list_res["memories"]
    assert len(memories) == 1
    assert memories[0]["key"] == "assistant_info"
    assert memories[0]["content"] == "Antigravity is a pair programming AI assistant."
    assert memories[0]["category"] == "general"
    assert memories[0]["tags"] == ["ai", "pair-programming"]

    # Updating same memory
    update_args = RememberArgs(
        content="Antigravity is a super powerful pair programming AI assistant.",
        key="assistant_info",
        category="general",
        tags=["ai", "power"],
    )
    update_res_str = await remember(update_args)
    update_res = json.loads(update_res_str)
    assert update_res["action"] == "updated"

    # Verify update
    list_res_str = await list_memories(list_args)
    list_res = json.loads(list_res_str)
    memories = list_res["memories"]
    assert len(memories) == 1
    assert (
        memories[0]["content"] == "Antigravity is a super powerful pair programming AI assistant."
    )
    assert memories[0]["tags"] == ["ai", "power"]


@pytest.mark.asyncio
async def test_forget():
    """Test deleting memories."""
    # Add a memory
    args = RememberArgs(content="To forget soon.", key="ephemeral")
    await remember(args)

    # Forget by key
    forget_args = ForgetArgs(key="ephemeral")
    res_str = await forget(forget_args)
    res = json.loads(res_str)
    assert res["status"] == "success"
    assert res["deleted"] is True

    # Confirm deleted
    list_res_str = await list_memories(ListMemoriesArgs())
    list_res = json.loads(list_res_str)
    assert len(list_res["memories"]) == 0

    # Forget non-existent key
    res_str = await forget(ForgetArgs(key="non-existent"))
    res = json.loads(res_str)
    assert res["deleted"] is False

    # Forget without args
    res_str = await forget(ForgetArgs())
    res = json.loads(res_str)
    assert res["status"] == "error"


@pytest.mark.asyncio
async def test_recall():
    """Test memory retrieval via local BM25 full-text ranking."""
    # Insert facts
    await remember(
        RememberArgs(content="Python was created by Guido van Rossum.", key="py_creator")
    )
    await remember(
        RememberArgs(content="Vector search finds semantic similarities.", key="vector_info")
    )
    await remember(
        RememberArgs(content="Ansible is a configuration management tool.", key="ansible_info")
    )

    # Full-text search ranks the best lexical match first.
    recall_args = RecallArgs(query="Python Guido")
    res_str = await recall(recall_args)
    res = json.loads(res_str)
    assert len(res["results"]) > 0
    assert res["results"][0]["key"] == "py_creator"

    # A multi-word query surfaces the memory sharing those terms.
    semantic_args = RecallArgs(query="semantic vector", limit=2)
    semantic_res = json.loads(await recall(semantic_args))
    assert len(semantic_res["results"]) > 0
    assert semantic_res["results"][0]["key"] == "vector_info"

    # A query with no shared terms returns nothing.
    no_match = json.loads(await recall(RecallArgs(query="kubernetes helm chart")))
    assert no_match["results"] == []

    # Test tag/category filters
    await remember(
        RememberArgs(
            content="Testing filter tags.", key="filter_me", category="test", tags=["special"]
        )
    )
    tagged_recall = RecallArgs(query="Testing", category="test", tags=["special"])
    tagged_res = json.loads(await recall(tagged_recall))
    assert len(tagged_res["results"]) == 1
    assert tagged_res["results"][0]["key"] == "filter_me"

    # Tag filter mismatch
    mismatched_recall = RecallArgs(query="Testing", tags=["unrelated"])
    mismatched_res = json.loads(await recall(mismatched_recall))
    assert len(mismatched_res["results"]) == 0


@pytest.mark.asyncio
async def test_forget_by_id():
    """Test deleting memory by database ID."""
    await remember(RememberArgs(content="Delete by ID text.", key="del_by_id"))
    list_res = json.loads(await list_memories(ListMemoriesArgs()))
    mem = list_res["memories"][0]
    mem_id = mem["id"]

    # Forget by ID
    res = json.loads(await forget(ForgetArgs(id=mem_id)))
    assert res["status"] == "success"
    assert res["deleted"] is True


def test_get_max_content_chars(monkeypatch):
    """The content cap reads env, rejects junk, and treats non-positive as disabled."""
    from mcp_servers.memory.tools.db import DEFAULT_MAX_CONTENT_CHARS, get_max_content_chars

    monkeypatch.delenv("MCP_MEMORY_MAX_CONTENT_CHARS", raising=False)
    assert get_max_content_chars() == DEFAULT_MAX_CONTENT_CHARS

    monkeypatch.setenv("MCP_MEMORY_MAX_CONTENT_CHARS", "notanint")
    assert get_max_content_chars() == DEFAULT_MAX_CONTENT_CHARS

    monkeypatch.setenv("MCP_MEMORY_MAX_CONTENT_CHARS", "-5")
    assert get_max_content_chars() == 0

    monkeypatch.setenv("MCP_MEMORY_MAX_CONTENT_CHARS", "123")
    assert get_max_content_chars() == 123


@pytest.mark.asyncio
async def test_recall_truncates_large_content(monkeypatch):
    """recall caps returned content and reports the true length."""
    monkeypatch.setenv("MCP_MEMORY_MAX_CONTENT_CHARS", "50")
    big = "x" * 500 + " keyword"
    await remember(RememberArgs(content=big, key="big"))

    res = json.loads(await recall(RecallArgs(query="keyword")))
    item = res["results"][0]
    assert len(item["content"]) == 50
    assert item["content_truncated"] is True
    assert item["content_length"] == len(big)


@pytest.mark.asyncio
async def test_list_memories_truncates_large_content(monkeypatch):
    """list_memories caps returned content identically to recall."""
    monkeypatch.setenv("MCP_MEMORY_MAX_CONTENT_CHARS", "10")
    await remember(RememberArgs(content="A" * 100, key="big"))

    res = json.loads(await list_memories(ListMemoriesArgs()))
    mem = res["memories"][0]
    assert len(mem["content"]) == 10
    assert mem["content_truncated"] is True
    assert mem["content_length"] == 100


@pytest.mark.asyncio
async def test_truncation_disabled(monkeypatch):
    """Setting the cap to 0 returns full content with no truncation markers."""
    monkeypatch.setenv("MCP_MEMORY_MAX_CONTENT_CHARS", "0")
    content = "B" * 5000
    await remember(RememberArgs(content=content, key="big"))

    res = json.loads(await list_memories(ListMemoriesArgs()))
    mem = res["memories"][0]
    assert mem["content"] == content
    assert "content_truncated" not in mem


def test_ensure_initialized_runs_once(monkeypatch):
    """Schema init runs a single time per database path across connections."""
    from mcp_servers.memory.tools import db

    calls = 0
    orig_init = db.init_db

    def counting_init(conn):
        nonlocal calls
        calls += 1
        orig_init(conn)

    monkeypatch.setattr(db, "init_db", counting_init)
    db._initialized_paths.discard(db.DB_PATH)

    with db.get_db_conn(read_only=False):
        pass
    with db.get_db_conn(read_only=False):
        pass

    assert calls == 1


def test_db_connection_conflict_retry(monkeypatch):
    """Connection-open conflict/constraint errors (e.g. cold-start catalog races) retry."""
    import duckdb

    from mcp_servers.memory.tools.db import get_db_conn

    attempts = 0
    orig_connect = duckdb.connect

    def mock_connect(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise duckdb.IOException("Catalog write-write conflict on create")
        return orig_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", mock_connect)
    monkeypatch.setattr("time.sleep", lambda s: None)

    with get_db_conn() as conn:
        assert conn is not None
    assert attempts == 2


def test_db_caller_exception_propagates_cleanly():
    """An exception raised inside the `with` body propagates as-is.

    Regression test: the retry loop must not try to re-yield after an exception is
    thrown into the generator (which would raise `RuntimeError: generator didn't stop
    after throw()` and mask the real error). Even an error whose message matches the
    connection-retry substrings must surface unchanged from the caller's body.
    """
    import duckdb

    from mcp_servers.memory.tools.db import get_db_conn

    with (
        pytest.raises(duckdb.ConstraintException, match="unique constraint"),
        get_db_conn(read_only=False),
    ):
        raise duckdb.ConstraintException("Duplicate key violates unique constraint")


@pytest.mark.asyncio
async def test_remember_same_key_is_atomic_upsert():
    """Re-remembering a key updates in place via upsert — one row, no duplicate-key error."""
    await remember(RememberArgs(content="first", key="dup"))
    res = json.loads(await remember(RememberArgs(content="second", key="dup")))
    assert res["action"] == "updated"

    listed = json.loads(await list_memories(ListMemoriesArgs()))
    rows = [m for m in listed["memories"] if m["key"] == "dup"]
    assert len(rows) == 1
    assert rows[0]["content"] == "second"


def test_db_lock_handling(monkeypatch):
    """Test that db lock detection successfully retries and backsoff."""
    import duckdb

    from mcp_servers.memory.tools.db import get_db_conn

    attempts = 0
    orig_connect = duckdb.connect

    def mock_connect(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise duckdb.IOException("database is locked")
        return orig_connect(*args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", mock_connect)
    monkeypatch.setattr("time.sleep", lambda s: None)

    with get_db_conn() as conn:
        assert conn is not None
    assert attempts == 3


@pytest.mark.asyncio
async def test_recall_falls_back_without_fts(monkeypatch):
    """When the FTS index is unavailable, recall uses lexical token-overlap scoring."""
    import sys

    await remember(RememberArgs(content="Python was created by Guido van Rossum.", key="py"))
    await remember(RememberArgs(content="Ansible manages configuration.", key="ans"))

    # Force the FTS path to report "unavailable" so the lexical fallback runs.
    # tools/__init__ shadows the submodule attribute, so reach it via sys.modules.
    recall_mod = sys.modules["mcp_servers.memory.tools.recall"]
    monkeypatch.setattr(recall_mod, "_fts_ranked_rows", lambda conn, args: None)

    res = json.loads(await recall(RecallArgs(query="Python Guido")))
    assert len(res["results"]) > 0
    assert res["results"][0]["key"] == "py"


@pytest.mark.asyncio
async def test_list_memories_pagination():
    """Test pagination offset and limit functionality in list_memories."""
    # Insert multiple facts
    for i in range(5):
        await remember(
            RememberArgs(content=f"Fact number {i}", key=f"key_{i}", category="pagination")
        )

    # Verify offset=0, limit=2 returns first 2
    list_args_1 = ListMemoriesArgs(category="pagination", limit=2, offset=0)
    res_1 = json.loads(await list_memories(list_args_1))
    assert len(res_1["memories"]) == 2
    keys_1 = [m["key"] for m in res_1["memories"]]

    # Verify offset=2, limit=2 returns next 2
    list_args_2 = ListMemoriesArgs(category="pagination", limit=2, offset=2)
    res_2 = json.loads(await list_memories(list_args_2))
    assert len(res_2["memories"]) == 2
    keys_2 = [m["key"] for m in res_2["memories"]]

    # Verify no intersection between pages
    assert not set(keys_1).intersection(set(keys_2))

    # Verify offset=4, limit=2 returns remaining 1
    list_args_3 = ListMemoriesArgs(category="pagination", limit=2, offset=4)
    res_3 = json.loads(await list_memories(list_args_3))
    assert len(res_3["memories"]) == 1
    assert res_3["memories"][0]["key"] not in keys_1
    assert res_3["memories"][0]["key"] not in keys_2
