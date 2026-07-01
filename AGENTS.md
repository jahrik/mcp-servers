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
├── _common/          # shared helpers (gh runner, input validation) — reuse, don't copy
├── github/           # read-only GitHub server (gh-backed) → mcp-github
└── <next>/           # future servers live here
tests/
.github/workflows/ci.yml
```

## Conventions

- **Tooling:** `uv` for deps/venv; `ruff` for lint + format; `ty` for type checking;
  `pytest` for tests; `pre-commit` as the local gate wiring them together.
- **Python:** 3.12+, type hints preferred, `from __future__ import annotations`.
- **Servers are thin:** a server maps agent-facing tools onto an underlying CLI/API. Keep
  domain logic minimal; push shared plumbing into `_common`.
- **Default to read-only.** Add write/mutating tools deliberately, as separate `@mcp.tool()`
  functions, never as a side effect of a read tool.
- **Security:** never build shell strings from model input — always pass an **argv list**
  to `subprocess` (no `shell=True`). Validate identifiers (repo slugs, refs) before use.
  Never write a secret to a file; reuse the underlying tool's existing auth
  (e.g. `github` inherits `gh auth login`).
- **No secrets, no hardcoded hosts/IPs** — same rules as the rest of the ecosystem.
- **Prefer MCP servers over raw CLI:** AI agents should prefer using the tools provided by the `mcp-github` server over executing raw `gh` commands, as raw CLI usage might fail due to insufficient permissions.

## Adding a server

1. `src/mcp_servers/<name>/server.py`: a `FastMCP("<name>")`, `@mcp.tool()` functions,
   and `def main(): mcp.run()`.
2. Add `<name> = "mcp_servers.<name>.server:main"` under `[project.scripts]`.
3. Reuse/extend `_common`; add tests under `tests/`; update the README server table.

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
