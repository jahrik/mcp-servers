# workspace

A read-only local git survey server for AI agents: one call answers "what's the state of my
workspace?" across every repo under one root, replacing ad-hoc `for repo in */` git loops.
It never mutates a working copy — every git invocation is a fixed-argv, read-only command.
Cleanup stays a human/agent decision made with the full report in hand.

Installed as `mcp-workspace`; registered as `ws` (Claude Code reserves the server name
`workspace`).

## Tools

### `ws_status`
Status of every git repo in the workspace root (one directory level deep): branch, upstream,
ahead/behind counts, staged/unstaged/untracked/conflict counts, stashes, and a `dirty` flag.

**Arguments**:
- `root` (string, optional): Workspace root to scan. Defaults to `$MCP_WORKSPACE_ROOT`, then `~/github`.
- `attention_only` (boolean, optional): Only return repos needing attention — dirty tree, ahead/behind upstream, stashes, or no upstream. Start here; it's the cheapest useful view.

### `ws_repo`
Detailed view of one repo: status, local branches with tracking info, and remotes.

**Arguments**:
- `path` (string, required): Repo path — absolute, `~`-relative, or relative to the workspace root.
- `root` (string, optional): Workspace root used to resolve a relative `path`.

### `ws_branches`
Stale-branch report across the workspace: branches whose upstream is gone (merged + deleted on
the remote), local-only branches, and branches already merged into the default branch. Repos
with nothing to report are omitted.

**Arguments**:
- `root` (string, optional): Workspace root to scan. Defaults to `$MCP_WORKSPACE_ROOT`, then `~/github`.

### `ws_log`
Recent commits across the workspace, newest first per repo — "what changed lately" without
per-repo `git log` loops. Commits are taken from local branches only; repos with no matching
commits are omitted.

**Arguments**:
- `root` (string, optional): Workspace root to scan. Defaults to `$MCP_WORKSPACE_ROOT`, then `~/github`.
- `path` (string, optional): Limit to one repo instead of scanning the whole root.
- `since` (string, optional): Only commits newer than this (git approxidate: `3 days`, `2026-07-01`). Defaults to `1 week`.
- `limit` (integer, optional): Max commits per repo (default `20`, max `200`).

## Configuration

- `MCP_WORKSPACE_ROOT`: Default root directory scanned for git repos. Falls back to `~/github`.
  Every tool also accepts a per-call `root` argument.

No credentials are needed: the server only reads local git state and never contacts a remote.

## Usage patterns

- **Session start / "where was I?"** — `ws_status` with `attention_only: true`, then `ws_log`
  for the last few days of commits.
- **Before cleanup** — `ws_branches` to gather the stale-branch report, then decide branch by
  branch; the server deliberately has no delete tool.
- **Digging into one repo** — `ws_repo` for its branches, tracking state, and remotes.
