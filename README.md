# mcp-servers

[![CI](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml/badge.svg)](https://github.com/jahrik/mcp-servers/actions/workflows/ci.yml)

A small collection of focused, self-maintained [MCP](https://modelcontextprotocol.io)
servers — curated tools for AI coding agents, kept deliberately narrow.

Each server lives as a subpackage under `src/mcp_servers/` and ships its own console
script, owning its own plumbing (HTTP client, validation, caching). One repo, one CI, one release.

## Servers

| Server   | Script       | What it does                                              |
| -------- | ------------ | --------------------------------------------------------- |
| `github` | `mcp-github` | GitHub access (PRs, issues, files, code search, review threads) |

### `github`

An async Python GitHub server. Authenticates via a GitHub App using Installation Access Tokens, providing clear audit attribution for AI agent actions.

[Read the detailed `github` server documentation](docs/github.md).

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
currently registers `github` via its `ai_agents_mcp_servers` variable (`type: stdio`,
`command: mcp-github`) but doesn't yet manage GitHub App credentials for you — that role still
assumes the old `gh auth login` model. Automated credential wiring for it is planned, not shipped;
until then, set the three env vars yourself as shown above.

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
