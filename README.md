# mcp-servers

[![CI](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml/badge.svg)](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml)

A small collection of focused, self-maintained [MCP](https://modelcontextprotocol.io)
servers — curated tools for AI coding agents, kept deliberately narrow.

Each server is a subpackage under `src/mcp_servers/` and ships its own console script,
owning its own plumbing (HTTP client, validation, caching). One repo, one CI, one release.

## Servers

| Server       | Script           | What it does                                                               |
| ------------ | ---------------- | ------------------------------------------------------------------------- |
| `github`     | `mcp-github`     | GitHub access as a GitHub App: PRs, issues, files, code search, reviews    |
| `workspace`  | `mcp-workspace`  | Read-only local git surveys: dirty trees, unpushed work, stale branches    |
| `data`       | `mcp-data`       | SQL over large local files and scratch tables across calls (DuckDB engine) |
| `dispatcher` | `mcp-dispatcher` | Asynchronous agent-to-agent task delegation and orchestration              |
| `lsp`        | `mcp-lsp`        | Multi-language LSP router plus tree-sitter: navigation, symbols, refactors |

Each server has detailed documentation under [`docs/`](docs/).

### `github`

GitHub access over REST and GraphQL, authenticated as a **GitHub App** so agent actions are
attributed to a dedicated bot identity (`app-name[bot]`). Reads are open; writes are gated behind
`MCP_GITHUB_ALLOW_WRITE=1` and recorded to a local SQLite audit log.

See [`docs/github.md`](docs/github.md) for the tool list and the one-time App setup walkthrough.

### `workspace`

A read-only survey of every git repo under one root (default `~/github`): branches, upstream
ahead/behind, dirty trees, stashes, and stale branches. It never mutates a working copy and needs
no credentials.

See [`docs/workspace.md`](docs/workspace.md).

### `data`

Local data analysis without burning agent context: run SQL over large CSV/JSON/JSONL/Parquet files
in place and keep scratch tables alive across tool calls, pulling only answer rows into the context
window. DuckDB is the engine, so the tools keep the `duckdb_*` prefix.

See [`docs/data.md`](docs/data.md).

### `dispatcher`

Asynchronous agent-to-agent task delegation: spawn and monitor background subagents for
long-running workflows, with job state tracked in SQLite. Spawning is gated behind
`MCP_DISPATCHER_ALLOW_SPAWN`.

See [`docs/dispatcher.md`](docs/dispatcher.md).

### `lsp`

A router that fronts real language servers (`pyright`, `gopls`, `rust-analyzer`,
`typescript-language-server`), spawning one per language on demand, so agents get IDE-grade
semantic answers — definitions, references, types, call flow, renames — without managing JSON-RPC
lifecycles. It also bundles offline tree-sitter tools (`ts_*`) for instant structural queries and
outlines. Prefer these over grep for anything semantic.

See [`docs/lsp.md`](docs/lsp.md).

## Install

```bash
# Install from git — this package is not published to PyPI.
uv tool install git+https://github.com/jahrik/mcp-servers

# Upgrade to the latest main later:
uv tool install --force git+https://github.com/jahrik/mcp-servers

# Or, from a checkout:
uv sync
```

The `github` server requires a GitHub App installed on the repos the agent should touch, with its
credentials exported as `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, and
`GITHUB_APP_PRIVATE_KEY`. See
[github.md § Setup](docs/github.md#setup-create-and-install-the-github-app) for the full
walkthrough. The other servers need no credentials.

## Register with an agent

Any MCP client can launch a server over stdio. For `github`, pass the three `GITHUB_APP_*`
variables into the server's environment — for Claude Code:

```bash
claude mcp add-json --scope user github '{
  "command": "mcp-github",
  "args": [],
  "env": {
    "GITHUB_APP_ID": "123456",
    "GITHUB_APP_INSTALLATION_ID": "78901234",
    "GITHUB_APP_PRIVATE_KEY": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
  }
}'
```

Pull the values from wherever you store the secret (password manager, `pass`, vault) rather than
pasting the key inline.

The [`ansible-ai-agents`](https://github.com/jahrik/ansible-ai-agents) role registers these servers
and manages the App identity for you: set the `ai_agents_mcp_github_app_*` vars and the role writes
an env file (App and installation IDs plus the *path* to your PEM, mode 0600) and a wrapper that
exports the key at launch — no config file ever holds the key itself.

## Development

```bash
uv sync
uv run pre-commit install        # once per clone
uv run ruff check .
uv run ruff format .
uv run ty check
uv run pytest
uvx pre-commit run --all-files   # every gate, as CI runs it
```

CI runs ruff (check + format), `ty`, and pytest on every PR. Test coverage is gated at 90%
(`--cov-fail-under=90`). Tests use `pytest` + `pytest-mock` (no `unittest`) and stay real —
mocking only at I/O boundaries; CI installs `pyright` so the `integration`-marked language-server
tests run for real.

### Adding a server

1. Create `src/mcp_servers/<name>/server.py` with a `FastMCP` instance and a `main()` that calls
   `mcp.run()`. Define `@mcp.tool()` functions directly for small servers; for larger ones, put
   them in a `tools/` module and register them in `server.py`.
2. Keep shared plumbing (HTTP client, validation, caching) in that server's own module — there is
   no cross-server `_common` package.
3. Add the console script under `[project.scripts]` in `pyproject.toml`.
4. Add tests under `tests/`, a row to the table above, and a doc under `docs/`.

### Versioning and releases

Versioning is dynamic, driven by Git tags via `hatch-vcs`. To cut a release, tag and push:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The build derives the package version from the tag.

## License

MIT
