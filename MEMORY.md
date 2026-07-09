# MEMORY.md — mcp-memory status & open work

`mcp-memory` is a DuckDB-backed, cross-session long-term memory server (Claude Code + AGY, stdio MCP), storing to a persistent database at `~/.mcp/memory.db`. **Built and merged** (PR #55). Tools: `remember`, `recall`, `forget`, `list_memories`, `sync_existing_data`.

Design rationale, schema, and package layout now live in the code under `src/mcp_servers/memory/`; full stress-test methodology and metrics are in [RESULTS.md](file:///home/deck/github/mcp-servers/RESULTS.md). This file tracks only current status and outstanding work.

## Status

- Schema (`memories` table: `id`, `key`, `content`, `category`, `tags`, `created_at`, `updated_at`) created and verified. Search is fully local via a DuckDB `fts` BM25 index; no embedding column, no API keys.
- Live sync via `sync_existing_data` populated **54 records** (48 conversation summaries, 3 Claude sessions, 3 brain artifacts).
- Concurrency is strong once initialized: 150 concurrent distinct-key writes at 100% in 0.77s; 5 MB payloads write/read in ~0.1s.

## Resolved on branch `fix/mcp-memory-known-issues`

1. **Schema-init write-write conflict.** Schema now initializes once at server startup (`server.py:main`) and `ensure_initialized` serializes it per DB path with a lock, so concurrent cold-start writes can't race on `CREATE TABLE`. (RESULTS.md §Issue A / Rec 1.)
2. **Retry loop missed transaction/constraint errors.** `get_db_conn` now catches `duckdb.Error` and retries on `conflict`/`constraint` substrings too, so same-key write conflicts back off and retry (retried txn does UPDATE instead of INSERT). (RESULTS.md §Issue B / Rec 2.)
3. **`recall`/`list_memories` output cap.** Per-memory content is truncated to `MCP_MEMORY_MAX_CONTENT_CHARS` (default 2000; `0` disables), with `content_truncated`/`content_length` flags. A single large memory can no longer overflow the caller's context.
4. **Cloud-embedding dependency removed.** Dropped the Gemini/OpenAI `client.py` and the `embedding` column entirely. Recall now uses a local BM25 full-text index (DuckDB `fts`) with a lexical token-overlap fallback — fully offline, no API token. (Decision: local-only tool shouldn't call a cloud API.)

Tests: 468 pass; ruff + ty clean. Pending: PR + maintainer merge.
