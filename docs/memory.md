# memory

Persistent, cross-session long-term memory for AI agents: store facts, preferences, project
notes, and instructions, then recall them in later sessions. Backed by a DuckDB database at
`~/.mcp/memory.db` and usable by both Claude Code and Antigravity over stdio.

Installed as `mcp-memory`; registered as `memory`.

## Behavior

- **Durable memories** — `remember` stores a fact with an optional unique `key`, `category`, and `tags`; re-using a `key` overwrites the prior value.
- **Search** — `recall` ranks memories by relevance using a local BM25 full-text index (DuckDB `fts`), falling back to keyword + token-overlap scoring when the index is unavailable. Fully offline; no API keys, no network calls. See [Search modes](#search-modes).
- **Concurrency** — every tool call opens a connection, runs, and closes it. Schema initialization runs once at server startup and is serialized per database path, and the connection helper retries transient lock, catalog-conflict, and constraint errors with jittered exponential backoff.
- **Context safety** — `recall` and `list_memories` cap each memory's returned `content` (see `MCP_MEMORY_MAX_CONTENT_CHARS`) so a single large memory cannot flood the agent's context window.
- **Backfill** — `sync_existing_data` imports historical context (Antigravity brain artifacts, conversation summaries, and Claude session logs) into the store.

## Tools

### `remember`
Store a new memory or update an existing one that shares the same `key`.

**Arguments**:
- `content` (string, required): The fact, preference, detail, or instruction to remember.
- `key` (string, optional): Unique lookup key; re-using it overwrites the existing memory.
- `category` (string, optional): Category classification (e.g. `preferences`, `project_notes`, `tool_tips`).
- `tags` (array of strings, optional): Labels for grouping and filtered recall.

### `recall`
Search stored memories relevant to a query.

**Arguments**:
- `query` (string, required): Search term or query text.
- `category` (string, optional): Restrict to a category.
- `tags` (array of strings, optional): Restrict to memories matching any of these tags.
- `limit` (integer, optional): Maximum results (default `5`, max `100`).

Each returned memory's `content` is truncated to `MCP_MEMORY_MAX_CONTENT_CHARS`; when that happens the result includes `content_truncated: true` and `content_length` (the full length in characters).

### `forget`
Delete a memory by `key` or `id` (one is required).

**Arguments**:
- `key` (string, optional): The unique lookup key.
- `id` (string, optional): The unique database ID.

### `list_memories`
List stored memories, most recently updated first. Content is capped identically to `recall`.

**Arguments**:
- `category` (string, optional): Restrict to a category.
- `limit` (integer, optional): Maximum results (default `50`, max `1000`).
- `offset` (integer, optional): Number of memories to skip, for pagination.

### `sync_existing_data`
Scan and import historical context into the memory database.

**Arguments**:
- `dry_run` (boolean, optional): Preview the import without writing. Defaults to `false`.
- `brain_dir` (string, optional): Antigravity brain directory (default `~/.gemini/antigravity-cli/brain`).
- `summaries_db` (string, optional): Antigravity conversation-summaries SQLite database (default `~/.gemini/antigravity-cli/conversation_summaries.db`).
- `claude_dir` (string, optional): Claude projects directory (default `~/.claude/projects`).

## Search modes

Search is **fully local** — no embedding provider, API key, or per-query network call. Memory
content never leaves the machine.

- **BM25 full-text (default).** DuckDB's `fts` extension indexes memory `content` and `key`; `recall` ranks results by BM25 relevance. The index is a snapshot, so it is rebuilt after every write (`remember`, `forget`, `sync_existing_data`) to stay current.
- **Lexical fallback.** If the `fts` extension cannot be loaded — e.g. the very first use on a machine that is offline before DuckDB has cached the extension — `recall` transparently falls back to substring + token-overlap scoring. Results are still returned; only the ranking quality differs.

Because scoring is lexical/keyword-based (not embeddings), `recall` matches shared terms rather
than paraphrases: query with words that appear in the memory, or use `tags`/`category` filters to
narrow the set. The one-time `fts` extension download is cached under `~/.duckdb/extensions` and,
unlike the previous cloud-embedding path, sends no memory content anywhere.

## Configuration

Configuration parameters are read from environment variables:

- `MCP_MEMORY_MAX_CONTENT_CHARS`: Per-memory content cap for `recall`/`list_memories` output (default `2000`). Prevents a single large synced memory (e.g. a 64 KB session log) from overflowing the caller's context window. Set to `0` (or any non-positive value) to disable truncation.
- `MCP_LOG_LEVEL`: Logging verbosity (default `WARNING`). Set to `DEBUG` to log when the full-text index is unavailable and recall is using the lexical fallback.

Storage lives at `~/.mcp/memory.db`; the parent directory is created on first use.
