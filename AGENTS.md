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
├── github/           # GitHub server (async httpx + GitHub App Auth) → mcp-github
│   ├── auth.py       # JWT + Installation Access Token exchange
│   ├── client.py     # shared httpx wrapper, validation, pagination — reuse, don't copy
│   └── tools/        # one module per tool group (prs, issues, actions, reviews, ...)
└── <next>/           # future servers live here
tests/
.github/workflows/ci.yml
```

## Conventions

- **Tooling:** `uv` for deps/venv; `ruff` for lint + format; `ty` for type checking;
  `pytest` for tests; `pre-commit` as the local gate wiring them together.
- **Python:** 3.12+, type hints preferred, `from __future__ import annotations`.
- **Servers are thin:** a server maps agent-facing tools onto an underlying CLI/API. Keep
  domain logic minimal; push shared plumbing into that server's own `client.py`/`utils.py`
  (there is no cross-server `_common` package — each server owns its plumbing).
- **Default to read-only.** Add write/mutating tools deliberately, as separate `@mcp.tool()`
  functions, never as a side effect of a read tool.
- **Security:** use standard HTTP clients (e.g. `httpx`). Validate identifiers (repo slugs, refs) before use. Never write a secret to a file; authenticate via injected environment variables (e.g. GitHub App Installation Access Tokens).
- **No secrets, no hardcoded hosts/IPs** — same rules as the rest of the ecosystem.
- **Prefer MCP servers over raw CLI:** AI agents should prefer using the tools provided by the `mcp-github` server over executing raw `gh` commands, as raw CLI usage might fail due to insufficient permissions.

## Adding a server

1. `src/mcp_servers/<name>/server.py`: a `FastMCP("<name>")` entry point and `def main(): mcp.run()`.
2. For small servers, put `@mcp.tool()` functions directly in `server.py`. For larger servers, extract logic into a `tools/` directory and register them in `server.py`.
3. Add `<name> = "mcp_servers.<name>.server:main"` under `[project.scripts]`.
4. Add tests under `tests/`; update the README server table.

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

CI runs ruff (check + format), `ty`, and pytest on every PR.
