# MEMORY.md — mcp-memory Implementation Plan

This document outlines the design and step-by-step plan for building **`mcp-memory`**, a DuckDB-backed, cross-session long-term memory server.

---

## 1. Architectural Goals

- **Persistence:** All memory data must be saved to a persistent DuckDB database at `~/.mcp/memory.db`.
- **Cross-client compatibility:** Fully usable by both Claude Code and Antigravity (AGY) via the stdio MCP protocol.
- **Concurrency & Lock Handling:**
  - Because DuckDB restricts database writes to a single process at a time, we will **not** keep database connections cached or open across tool calls.
  - Every tool execution will open a connection, perform its query, and immediately close it.
  - To prevent concurrent lock failures between multiple agents (e.g. Claude and AGY), we will implement an automatic retry decorator with jittered exponential backoff (e.g., 5 attempts over up to 2 seconds).
- **Search Capabilities:**
  - Full-Text Search (FTS) / Substring search (default, local, zero-config).
  - Optional Vector Semantic Search using DuckDB's native array capabilities. If an embedding provider is configured (e.g. Gemini via `GEMINI_API_KEY`), we can compute embeddings of facts and perform cosine similarity searches.
- **Pydantic Validation:** All tools must conform to frozen Pydantic models with clear description fields.
- **Async Safety:** Run blocking DuckDB operations in worker threads via `asyncio.to_thread`.

---

## 2. Database Connection Strategy & Schema

Every database operation will execute through a connection manager helper that implements retries when encountering locking errors (`duckdb.IOException` or file lock errors).

### Concurrency Helper Example

```python
import time
import random
import duckdb

def execute_with_retry(db_path, query, params=None, read_only=False, max_retries=5):
    last_err = None
    for attempt in range(max_retries):
        try:
            with duckdb.connect(database=db_path, read_only=read_only) as conn:
                if params:
                    return conn.execute(query, params).fetchall()
                else:
                    return conn.execute(query).fetchall()
        except duckdb.IOException as e:
            if "lock" in str(e).lower() or "permission" in str(e).lower():
                last_err = e
                # Jittered exponential backoff: 0.1s, 0.2s, 0.4s, 0.8s ...
                sleep_time = (0.1 * (2 ** attempt)) + random.uniform(0, 0.05)
                time.sleep(sleep_time)
                continue
            raise e
    raise RuntimeError(f"Database locked after {max_retries} attempts: {last_err}")
```

### Table: `memories`

```sql
CREATE TABLE IF NOT EXISTS memories (
    id VARCHAR PRIMARY KEY,         -- Unique ID (UUID or content hash)
    key VARCHAR,                    -- Optional user-specified lookup key
    content TEXT NOT NULL,          -- The memory text / fact
    category VARCHAR,               -- e.g., 'preferences', 'project_notes', 'tool_tips'
    tags VARCHAR,                   -- JSON array of tags, e.g., '["python", "ansible"]'
    embedding FLOAT[],              -- Optional float array for vector search
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Tool Definitions

The server will register 4 core tools:

### `remember`
Insert a new memory or update an existing one matching the specified `key` or `id`.
- **Arguments:**
  - `content` (string, required): The fact or instruction.
  - `key` (string, optional): A unique identifier for lookup/replacement.
  - `category` (string, optional): Category classification.
  - `tags` (array of strings, optional): Arbitrary labels.
- **Returns:** Confirmation JSON payload.

### `recall`
Search saved memories using keyword or semantic similarity.
- **Arguments:**
  - `query` (string, required): Search term.
  - `category` (string, optional): Filter by category.
  - `tags` (array of strings, optional): Filter by tags.
  - `limit` (int, default=5): Maximum records to return.
- **Returns:** List of matching memory records.

### `forget`
Delete a memory by `key` or `id`.
- **Arguments:**
  - `key` (string, optional): The unique lookup key.
  - `id` (string, optional): The unique ID.
- **Returns:** Confirmation of deletion.

### `list_memories`
List saved memories, optionally filtering by category.
- **Arguments:**
  - `category` (string, optional): Filter by category.
  - `limit` (int, default=50): Max records to retrieve.
- **Returns:** List of memory records.

### `sync_existing_data`
Scan `/home/deck/.gemini/antigravity-cli/brain/` for user/agent artifacts (such as plans, reports, etc.), `conversation_summaries.db` for conversation previews, and `~/.claude/projects/` for Claude Code session logs, and sync them into the long-term memory database `~/.mcp/memory.db`.
- **Arguments:**
  - `dry_run` (boolean, default=False): If True, only lists what would be imported without writing to the database.
  - `brain_dir` (string, optional): Absolute path to the brain directory. Defaults to `~/.gemini/antigravity-cli/brain`.
  - `summaries_db` (string, optional): Absolute path to the summaries SQLite database. Defaults to `~/.gemini/antigravity-cli/conversation_summaries.db`.
  - `claude_dir` (string, optional): Absolute path to the Claude projects directory. Defaults to `~/.claude/projects`.
- **Returns:** JSON summary of imported items (e.g. number of artifacts imported, number of conversation summaries imported, number of Claude session turns imported).

---

## 4. Package Structure

We will add a new subpackage inside `src/mcp_servers/`:

```
src/mcp_servers/memory/
├── __init__.py
├── server.py             # FastMCP application and script entry point
├── client.py             # Embedding API client (Gemini / OpenAI fallback)
├── models/
│   ├── __init__.py
│   └── schemas.py        # Pydantic input argument schemas
└── tools/
    ├── __init__.py
    ├── forget.py
    ├── list_memories.py
    ├── recall.py
    ├── remember.py
    └── sync.py           # Sync logic for brain artifacts & conversation summaries
```

---

## 5. Implementation Phases

### Phase 1: Models & Entry Point
- Add schemas under `src/mcp_servers/memory/models/schemas.py`.
- Define console script `mcp-memory = "mcp_servers.memory.server:main"` in `pyproject.toml`.

### Phase 2: Embeddings Client (Optional)
- Add a client in `client.py` that checks for `GEMINI_API_KEY` (using Gemini embedding model) or falls back to BM25/FTS if no API key is present.

### Phase 3: DB & Tools Implementation
- Implement DB connection helper mapping `~/.mcp/memory.db`.
- Implement `remember`, `recall`, `forget`, and `list_memories`.
- Implement `sync_existing_data` to parse markdown files (excluding `.system_generated` logs except where explicitly needed, focusing on `.md` user-facing artifacts), `conversation_summaries.db`, and Claude session logs under `~/.claude/projects/`.
- Ensure all queries use `asyncio.to_thread` to prevent event-loop blockage.

### Phase 4: Unit Testing
- Write tests under `tests/memory/` using `pytest`.
- Use a temporary database file or `:memory:` for isolation.
- Add sample tests for importing dummy markdown files and dummy SQLite databases.

### Phase 5: Client Configuration
- Document how to add the server to `claude_config.json` and AGY config.
