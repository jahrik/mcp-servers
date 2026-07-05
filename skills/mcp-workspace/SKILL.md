---
name: mcp-workspace
description: Survey the local git workspace with mcp-workspace tools instead of ad-hoc git/ls loops. Use when checking repo status, dirty trees, unpushed work, or stale branches across ~/github.
---

# Workspace Surveys via MCP

When answering "what state are my repos in?" questions — dirty trees, unpushed
commits, stale branches — **prefer the `mcp-workspace` tools over ad-hoc
`git`/`ls` loops in the shell**. One tool call replaces a per-repo loop and
returns compact JSON.

## Tools

- `ws_status` — every repo under the root (default `~/github`, override with
  `root` or `$MCP_WORKSPACE_ROOT`): branch, upstream, ahead/behind, dirty
  counts, stashes. `attention_only: true` filters to repos needing action.
- `ws_repo` — one repo in depth: status plus all local branches with tracking
  info and remotes.
- `ws_branches` — stale-branch report across the workspace: upstreams gone,
  local-only branches, branches already merged into the default branch.
- `ws_log` — recent commits across the workspace or one repo (`path`), local
  branches only; `since` takes git approxidate ("3 days", "2026-07-01").

## Rules

- The server is **read-only** — it reports, you decide. Any cleanup (branch
  deletion, push, stash pop) is a separate, deliberate action.
- Report **all** findings to the user; never silently filter items out of a
  sweep. `attention_only` narrows the query, not the honesty of the report.
- Start with `ws_status` (`attention_only: true`); reach for `ws_branches`
  when the question is about branch cleanup, and `ws_repo` for a single repo.
