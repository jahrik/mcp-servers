from __future__ import annotations

import json
import sqlite3

import pytest

from mcp_servers.memory.models.schemas import (
    ForgetArgs,
    ListMemoriesArgs,
    RecallArgs,
    RememberArgs,
    SyncExistingDataArgs,
)
from mcp_servers.memory.server import main, mcp
from mcp_servers.memory.tools import db
from mcp_servers.memory.tools.forget import forget
from mcp_servers.memory.tools.list_memories import list_memories
from mcp_servers.memory.tools.recall import recall
from mcp_servers.memory.tools.remember import remember
from mcp_servers.memory.tools.sync import sync_existing_data


@pytest.fixture(autouse=True)
def use_test_db(tmp_path, monkeypatch):
    """Override the database path to use a temp directory during testing."""
    test_db_path = str(tmp_path / "test_memory.db")
    monkeypatch.setattr(db, "DB_PATH", test_db_path)
    return test_db_path


@pytest.fixture
def mock_embedding(mocker):
    """Mock network calls for embeddings hermetically."""

    def _mock_get_embedding(text):
        if "vector" in text or "semantic" in text or "query" in text:
            # Return a simple 3-dimensional float array
            return [1.0, 0.0, 0.0]
        return None

    return mocker.patch("mcp_servers.memory.client.get_embedding", side_effect=_mock_get_embedding)


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
async def test_remember_and_list(mock_embedding):
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
async def test_recall(mock_embedding):
    """Test memory retrieval with text search and vector similarity fallback."""
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

    # Test Exact/Token overlap search
    recall_args = RecallArgs(query="Python Guido")
    res_str = await recall(recall_args)
    res = json.loads(res_str)
    assert len(res["results"]) > 0
    assert res["results"][0]["key"] == "py_creator"

    # Test Vector similarity search (which should trigger our mocked embedding helper)
    vector_recall_args = RecallArgs(query="semantic vector", limit=2)
    vector_res_str = await recall(vector_recall_args)
    vector_res = json.loads(vector_res_str)
    assert len(vector_res["results"]) > 0
    # Because we mocked embedding of "semantic" to return [1,0,0], and remember text contained "vector",
    # the vector search should match "vector_info" (which was stored with "vector" in content and thus got embedding [1,0,0]).
    assert vector_res["results"][0]["key"] == "vector_info"

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
async def test_sync_existing_data(tmp_path, mock_embedding):
    """Test importing artifacts, SQLite summaries, and Claude logs."""
    # 1. Setup mock brain artifacts directory
    brain_dir = tmp_path / "brain"
    conv_dir = brain_dir / "conv-123"
    conv_dir.mkdir(parents=True)
    with open(conv_dir / "plan.md", "w") as f:
        f.write("# Deployment Plan\nUse Ansible roles to configure Docker Swarm.")

    # A system generated file (should be skipped)
    sys_dir = conv_dir / ".system_generated"
    sys_dir.mkdir()
    with open(sys_dir / "system_log.md", "w") as f:
        f.write("System message.")

    # 2. Setup mock conversation summaries database
    summaries_db_path = str(tmp_path / "summaries.db")
    lite_conn = sqlite3.connect(summaries_db_path)
    lite_conn.execute(
        """
        CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            title TEXT,
            preview TEXT,
            step_count INTEGER,
            last_modified_time TEXT,
            workspace_uris TEXT
        )
        """
    )
    lite_conn.execute(
        "INSERT INTO conversation_summaries VALUES (?, ?, ?, ?, ?, ?)",
        (
            "conv-summary-456",
            "Refactor tests",
            "This conversation refactored workspace tests.",
            42,
            "2026-07-08T12:00:00",
            '["file:///home/deck/github/mcp-servers"]',
        ),
    )
    lite_conn.commit()
    lite_conn.close()

    # 3. Setup Claude projects session logs
    claude_dir = tmp_path / "claude"
    project_dir = claude_dir / "mcp-project"
    project_dir.mkdir(parents=True)

    jsonl_lines = [
        {"type": "ai-title", "aiTitle": "Sync project features"},
        {
            "type": "user",
            "message": {"role": "user", "content": "How do we write new MCP tools?"},
            "timestamp": "2026-07-08T13:00:00.000Z",
            "cwd": "/home/deck/github",
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Use the FastMCP python library."}],
            },
        },
    ]
    with open(project_dir / "session-789.jsonl", "w") as f:
        for line in jsonl_lines:
            f.write(json.dumps(line) + "\n")

    # Call dry run first
    sync_args = SyncExistingDataArgs(
        dry_run=True,
        brain_dir=str(brain_dir),
        summaries_db=summaries_db_path,
        claude_dir=str(claude_dir),
    )
    dry_res = json.loads(await sync_existing_data(sync_args))
    assert dry_res["dry_run"] is True
    assert dry_res["stats"]["brain_artifacts"] == 1
    assert dry_res["stats"]["conversation_summaries"] == 1
    assert dry_res["stats"]["claude_sessions"] == 1
    assert len(dry_res["preview"]) == 3

    # Call real sync
    real_sync_args = SyncExistingDataArgs(
        dry_run=False,
        brain_dir=str(brain_dir),
        summaries_db=summaries_db_path,
        claude_dir=str(claude_dir),
    )
    real_res = json.loads(await sync_existing_data(real_sync_args))
    assert real_res["dry_run"] is False
    assert real_res["imported"] == 3

    # Verify DB contents
    list_res = json.loads(await list_memories(ListMemoriesArgs(limit=10)))
    memories = list_res["memories"]
    assert len(memories) == 3

    keys = {m["key"] for m in memories}
    assert "brain/conv-123/plan.md" in keys
    assert "summary/conv-summary-456" in keys
    assert "claude/session-789" in keys

    # Verify content formatting
    claude_mem = next(m for m in memories if m["key"] == "claude/session-789")
    assert "Sync project features" in claude_mem["content"]
    assert "How do we write new MCP tools?" in claude_mem["content"]
    assert "Use the FastMCP python library." in claude_mem["content"]


def test_cosine_similarity_edge_cases():
    """Test recall.py cosine similarity error/edge cases."""
    from mcp_servers.memory.tools.recall import cosine_similarity

    assert cosine_similarity(None, None) == 0.0
    assert cosine_similarity([1.0], None) == 0.0
    assert cosine_similarity([1.0], [1.0, 2.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
    assert cosine_similarity([1.0, 1.0], [0.0, 0.0]) == 0.0


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


def test_client_embeddings(monkeypatch, httpx_mock):
    """Test the raw API requests for Gemini and OpenAI embeddings."""
    from mcp_servers.memory.client import get_embedding

    monkeypatch.setenv("GEMINI_API_KEY", "mock_gemini_key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    # Mock Gemini embedding response
    httpx_mock.add_response(
        url="https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key=mock_gemini_key",
        json={"embedding": {"values": [0.1, 0.2, 0.3]}},
    )

    res = get_embedding("hello gemini")
    assert res == [0.1, 0.2, 0.3]

    # Test OpenAI embedding fallback
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "mock_openai_key")

    httpx_mock.add_response(
        url="https://api.openai.com/v1/embeddings",
        json={"data": [{"embedding": [0.4, 0.5]}]},
    )

    res = get_embedding("hello openai")
    assert res == [0.4, 0.5]
