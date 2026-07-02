---
name: mcp-github
description: Best practices for interacting with GitHub. AI agents should prefer the mcp-github server tools over using raw gh commands to avoid permission failures.
---

# GitHub Interactions via MCP

When interacting with GitHub (e.g., listing PRs, reading issues, commenting, reviewing code), you should **always prefer using the tools exposed by the `mcp-github` server** over executing raw `gh` commands in the terminal.

## Why?

Agents run in sandboxed environments or might not have direct, interactive terminal access to authenticate `gh` correctly. Raw `gh` commands might fail due to insufficient permissions or missing authentication context in the active shell. The `mcp-github` server is configured by the host to access GitHub resources.

## Features

- **Schema Validation**: Uses Pydantic to validate inputs (like invalid repo names) before hitting the GitHub API, rejecting malformed inputs.
- **Enhanced Audit Logging**: The SQLite audit log captures execution duration, success status, and full stderr for complete observability.
- **Error Handling**: On failure, the server returns context rather than raw stack traces.

## Best Practices

- Check your available MCP servers for `mcp-github` tools (note: tools are prefixed with `gh_<command>_<action>`, e.g., `gh_pr_list`, `gh_issue_get`, `gh_search_code`).
- Use these tools via your MCP calling capabilities rather than spawning subprocesses with `run_command` or similar shell utilities.
- If an MCP tool provides the information you need, do not attempt to bypass it by using the CLI.
