# AGENTS.md

A Python monorepo of small MCP servers. AI agents working here should follow these
conventions.

## Purpose

Curated, self-maintained MCP servers for AI coding agents. Each server is a subpackage
under `src/mcp_servers/`, exposed as a console script, kept deliberately narrow. See
`README.md` for usage.

## Layout

```
src/mcp_servers/
├── github/           # GitHub App access (REST + GraphQL) → mcp-github
├── workspace/        # read-only local git surveys   → mcp-workspace
├── data/             # SQL over local files (DuckDB)  → mcp-data
├── dispatcher/       # async subagent job dispatch    → mcp-dispatcher
└── lsp/              # LSP router + tree-sitter        → mcp-lsp
tests/                # mirrors src/, per server
docs/                 # one page per server
.github/workflows/ci.yml
```

Each server subpackage follows the same shape: `server.py` (the `FastMCP` entry point and
`main()`), a `tools/` package (one module per tool group), a `models/` package (Pydantic
argument schemas), and its own plumbing (`client.py`, `utils.py`, `auth.py` as needed — the
`github` server's `auth.py` handles the JWT → Installation Access Token exchange).

## Conventions

- **Tooling:** `uv` for deps/venv; `ruff` for lint + format; `ty` for type checking;
  `pytest` for tests; `pre-commit` as the local gate wiring them together.
- **Python:** 3.12–3.13, type hints preferred. `from __future__ import annotations` is
  enforced repo-wide by ruff `I002` (isort `required-imports`).
- **Servers are thin:** a server maps agent-facing tools onto an underlying CLI/API. Keep
  domain logic minimal; push shared plumbing into that server's own `client.py`/`utils.py`
  (there is no cross-server `_common` package — each server owns its plumbing).
- **Tool arguments are Pydantic:** every `@mcp.tool()` takes a single frozen
  `*Args(BaseModel, frozen=True)` from that server's `models/schemas.py`, with per-field
  `Field(description=...)` and validation (`pattern`, `ge`/`le`, `Literal`). A tool needing
  the request context adds a trailing `ctx: Context` (injected by FastMCP, not part of the
  input schema).
- **Async vs sync:** use `async def` when the work is genuinely async I/O (`httpx.AsyncClient`,
  `asyncio.subprocess`) or offloads a blocking library via `await asyncio.to_thread(...)` (the
  `data` server does this for DuckDB). Do **not** call a blocking library directly from an
  `async def` tool, and do not "de-async" such a tool to a plain `def`: FastMCP runs sync tools
  **inline on the event loop**, so either would block the whole server.
- **Logging:** agent-facing output goes in the tool's return value; `logging` is the
  maintainer's diagnostic channel only. Each `main()` configures the root logger to **stderr**
  at `MCP_LOG_LEVEL` (default `WARNING`). Never log to stdout — it is the JSON-RPC channel.
- **Default to read-only.** Add write/mutating tools deliberately, as separate `@mcp.tool()`
  functions, never as a side effect of a read tool.
- **Security:** use standard HTTP clients (e.g. `httpx`). Validate identifiers (repo slugs, refs) before use. Never write a secret to a file; authenticate via injected environment variables (e.g. GitHub App Installation Access Tokens).
- **No secrets, no hardcoded hosts/IPs** — same rules as the rest of the ecosystem.
- **Prefer MCP servers over raw CLI:** AI agents should prefer using the tools provided by the `mcp-github` server over executing raw `gh` commands, as raw CLI usage might fail due to insufficient permissions.

## Adding a server

1. `src/mcp_servers/<name>/server.py`: a `FastMCP("<name>")` entry point and `def main(): mcp.run()`.
2. For small servers, put `@mcp.tool()` functions directly in `server.py`. For larger servers, extract logic into a `tools/` directory and register them in `server.py`.
3. Add `<name> = "mcp_servers.<name>.server:main"` under `[project.scripts]`.
4. Add tests under `tests/`, a `docs/<name>.md` page, and a row to the README server table.

## Commands

```bash
uv sync
uv run pre-commit install        # once per clone — runs the gates on commit
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
uvx pre-commit run --all-files   # run every gate, as CI would
```

CI runs ruff (check + format), `ty`, and pytest on every PR. Test coverage is gated at 90%
(`pytest --cov=src --cov-fail-under=90`).

**Testing conventions:** `pytest` + `pytest-mock` only — no `unittest`. Mock as little as
possible, and only at a true I/O boundary (subprocess spawn, the LSP child process); prefer
real objects everywhere else — real files under `tmp_path`, a real in-memory DuckDB, real git
repos in a temp dir, and `pytest-httpx` for the GitHub HTTP layer. Tests that drive a real
language server are marked `@pytest.mark.integration` and skip when it is absent; CI installs
`ty` so they run for real there.
