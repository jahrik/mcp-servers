# mcp-servers

[![CI](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml/badge.svg)](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml)

A small collection of focused, self-maintained [MCP](https://modelcontextprotocol.io)
servers — curated tools for AI coding agents, kept deliberately narrow.

Each server lives as a subpackage under `src/mcp_servers/` and ships its own console
script, owning its own plumbing (HTTP client, validation, caching). One repo, one CI, one release.

## Servers

| Server       | Script           | What it does                                                             |
| ------------ | ---------------- | ------------------------------------------------------------------------ |
| `github`     | `mcp-github`     | GitHub access (PRs, issues, files, code search, review threads)          |
| `workspace`  | `mcp-workspace`  | Local git workspace surveys (dirty trees, unpushed work, stale branches) |
| `data`       | `mcp-data`       | SQL over large local files + scratch tables across calls (DuckDB engine) |
| `dispatcher` | `mcp-dispatcher` | Asynchronous agent-to-agent task delegation and orchestration            |

### `github`

An async Python GitHub server. Authenticates via a GitHub App using Installation Access Tokens, providing clear audit attribution for AI agent actions.

[Read the detailed `github` server documentation](docs/github.md).

### `workspace`

A read-only local server: four tools (`ws_status`, `ws_repo`, `ws_branches`, `ws_log`) that survey
every git repo under one root (default `~/github`, override with `MCP_WORKSPACE_ROOT` or a
`root` argument) — dirty trees, ahead/behind upstreams, stashes, and stale branches. It never
mutates a working copy and needs no credentials.

[Read the detailed `workspace` server documentation](docs/workspace.md).

### `data`

Local data analysis without burning agent context: run SQL over large CSV/JSON/JSONL/Parquet
files in place and keep scratch tables alive across tool calls, pulling only answer rows into
the context window. Not a general database connector — it gives agents a computation escape
hatch and working memory outside the context window. DuckDB is the engine, so the tools keep
the `duckdb_*` prefix (the name tells the agent which SQL dialect and file-query idioms apply).

[Read the detailed `data` server documentation](docs/data.md).

### `dispatcher`

Asynchronous agent-to-agent task delegation and orchestration. Lets agents spawn and monitor background subagents for long-running workflows.

**Tools:**
- `submit_job` — persist a job and spawn a background worker to run it.
- `get_job_status` — fetch one job by id (status, payload, timestamps).
- `update_job_status` — set a job's status; terminal states are immutable.
- `list_jobs` — list jobs (optional status filter, `limit`), newest first.
- `cleanup_jobs` — delete terminal jobs, optionally only those older than N days.

**Configuration:**
- `MCP_DISPATCHER_ALLOW_SPAWN` (Required): Must be set to `"true"` or `"1"` to allow `submit_job` to spawn background processes.
- `MCP_DISPATCHER_DB_PATH`: Overrides the default SQLite database path (defaults to `~/.mcp/dispatcher.db`).
- `MCP_DISPATCHER_MAX_RUNNING`: Max concurrently-`Running` jobs before `submit_job` is refused (default `16`).

## Install

```bash
# Install from git — this package is not published to PyPI.
uv tool install git+https://github.com/jahrik/mcp-servers   # provides the mcp-github script

# Upgrade to the latest main later with:
uv tool install --force git+https://github.com/jahrik/mcp-servers

# or, from a checkout:
uv sync
```

Requires a GitHub App, installed on the repos you want the agent to touch, with its credentials
exported as `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, and `GITHUB_APP_PRIVATE_KEY`. See
[Setup: create and install the GitHub App](docs/github.md#setup-create-and-install-the-github-app)
for the full walkthrough (creating the App, generating a key, installing it, finding the
installation ID).

## Register with an agent

Any MCP client can launch a server over stdio. The client needs to pass the three
`GITHUB_APP_*` variables (see [Setup](docs/github.md#setup-create-and-install-the-github-app))
into the server's environment — for Claude Code:

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

Pull those values from wherever you actually store the secret (password manager, `pass`, vault)
rather than pasting the key inline — `add-json` just needs the final JSON.

If you use the [`ansible-ai-agents`](https://github.com/jahrik/ansible-ai-agents) role, it
registers `github` via its `ai_agents_mcp_servers` variable and manages the App identity for
you: set the three `ai_agents_mcp_github_app_*` vars and the role writes an env file (App and
installation IDs plus the *path* to your PEM, mode 0600) and a wrapper script that exports the
key at launch — no config file ever holds the key itself.

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

### Adding a server

1. Create `src/mcp_servers/<name>/server.py` with a `FastMCP` instance and a `main()` that calls `mcp.run()`.
   - For small servers, define `@mcp.tool()` functions directly in `server.py`.
   - For larger servers (like `github`), organize tools into a `tools/` module and import/register them in `server.py`.
2. Put shared plumbing (HTTP client, validation, caching) in that server's own module — there's
   no cross-server `_common` package.
3. Add the console script under `[project.scripts]` in `pyproject.toml`.
4. Add tests under `tests/` and a row to the table above.

### Versioning & Releases

This project uses `hatch-vcs` for dynamic versioning driven by Git tags. To create a new release:
1. Create a lightweight tag: `git tag v1.0.0`
2. Push the tag: `git push origin v1.0.0`
The package version will automatically be set to the tag name during build or installation.

## License

MIT
