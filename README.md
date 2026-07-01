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

A read-only GitHub server backed by the **`gh` CLI**. Because it shells out to `gh`, it
**reuses your existing `gh auth login` session** — no Personal Access Token, no secret in
any config file, no OAuth flow. If `gh` is logged in, the server works.

Read tools: `list_prs`, `get_pr`, `pr_diff`, `list_issues`, `get_issue`, `get_file`,
`search_code`, `list_review_comments`, `get_review_threads`.

Write tools: `reply_review_comment`, `resolve_review_thread` — the PR review-thread loop
(read a PR's inline comments, reply, resolve the thread). Write tools are added
deliberately, one at a time; the server never merges a PR or pushes to a default branch.

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

1. Create `src/mcp_servers/<name>/server.py` with a `FastMCP` instance, `@mcp.tool()`
   functions, and a `main()` that calls `mcp.run()`.
2. Reuse shared helpers from `mcp_servers._common` (add new ones there, not per-server).
3. Add the console script under `[project.scripts]` in `pyproject.toml`.
4. Add tests under `tests/` and a row to the table above.

## License

MIT
