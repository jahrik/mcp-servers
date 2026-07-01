# mcp-servers

[![CI](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml/badge.svg)](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml)

A small collection of focused, self-maintained [MCP](https://modelcontextprotocol.io)
servers — curated tools for AI coding agents, kept deliberately narrow.

Each server lives as a subpackage under `src/mcp_servers/` and ships its own console
script. One repo, one CI, one release — shared plumbing in `_common/`.

## Servers

| Server   | Script       | What it does                                              |
| -------- | ------------ | --------------------------------------------------------- |
| `github` | `mcp-github` | GitHub access (PRs, issues, files, code search, review threads) |

### `github`

A GitHub server backed by the **`gh` CLI**. Because it shells out to `gh`, it
**reuses your existing `gh auth login` session** — no Personal Access Token, no secret in
any config file, no OAuth flow. If `gh` is logged in, the server works.

Read tools: `gh_repo_list`, `gh_repo_get`, `gh_pr_list`, `gh_pr_get`, `gh_pr_diff`,
`gh_pr_checks`, `gh_issue_list`, `gh_issue_get`, `gh_file_get`, `gh_search_code`,
`gh_search_prs`, `gh_search_issues`, `gh_run_list`, `gh_run_get`, `gh_run_failed_logs`,
`gh_review_comments_list`, `gh_review_threads_get`, `gh_api_get`, `gh_graphql_query`.
The review-read tools take `bot_only` to keep just the Copilot/bot comments — the
actionable ones in a review.

Write tools: `gh_pr_create`, `gh_pr_comment`, `gh_pr_merge`, `gh_issue_create`,
`gh_issue_comment`, `gh_review_comment_reply`, `gh_review_thread_resolve`.
Every write tool invocation is recorded for accountability in a local SQLite audit log
at `~/.mcp/audit.db`.

#### Production Hardening

This server includes several features designed to make it robust and safe for AI agent use:
- **Rich Schema Validation**: Uses Pydantic to strictly validate inputs (e.g., repository names, issue numbers) before shelling out to `gh`, blocking malformed inputs.
- **Enhanced Audit Logging**: The SQLite audit log captures not just the command, but also the execution duration, success status, and full stderr for complete observability.
- **Actionable Error Handling**: On failure, the server returns AI-friendly hints and clear context rather than raw Python stack traces, helping agents self-correct.

## Install

```bash
# Install from git — this package is not published to PyPI.
uv tool install git+https://github.com/jahrik/mcp-servers   # provides the mcp-github script

# Upgrade to the latest main later with:
uv tool install --force git+https://github.com/jahrik/mcp-servers

# or, from a checkout:
uv sync
```

Requires the [`gh` CLI](https://cli.github.com/) on PATH and `gh auth login` completed.

## Register with an agent

Any MCP client can launch a server over stdio. For Claude Code:

```bash
claude mcp add-json --scope user github '{"command": "mcp-github", "args": []}'
```

The [`ansible-ai-agents`](https://github.com/jahrik/ansible-ai-agents) role wires these up
automatically via its `ai_agents_mcp_servers` variable (`type: stdio`, `command: mcp-github`).

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
2. Reuse shared helpers from `mcp_servers._common` (add new ones there, not per-server).
3. Add the console script under `[project.scripts]` in `pyproject.toml`.
4. Add tests under `tests/` and a row to the table above.

## License

MIT
