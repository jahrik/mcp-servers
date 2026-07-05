from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..git import WsError, find_repos, resolve_repo, resolve_root, run_git
from ..models.schemas import WsLogArgs

_FORMAT = "%h%x09%an%x09%ad%x09%s"


async def _repo_log(repo: Path, since: str, limit: int) -> dict[str, object] | None:
    out = await run_git(
        repo,
        "log",
        "--branches",
        f"--since-as-filter={since}",
        f"--max-count={limit}",
        "--date=short",
        f"--format={_FORMAT}",
    )
    commits = []
    for line in out.splitlines():
        sha, author, date, subject = line.split("\t", 3)
        commits.append({"sha": sha, "author": author, "date": date, "subject": subject})
    if not commits:
        return None
    return {"name": repo.name, "commits": commits}


async def ws_log(args: WsLogArgs) -> str:
    """Recent commits across the workspace, newest first per repo — "what changed
    lately" without per-repo git log loops. Repos with no matching commits are
    omitted. Commits are taken from local branches only.

    Args:
        root: Workspace root to scan. Defaults to $MCP_WORKSPACE_ROOT, then ~/github.
        path: Limit to one repo instead of scanning the whole root.
        since: Only commits newer than this (git approxidate, e.g. "3 days", "2026-07-01").
        limit: Max commits per repo.
    """
    if args.since.startswith("-"):
        raise WsError("`since` must be a date or relative age, not a flag")
    if args.path:
        repos = [resolve_repo(args.path, args.root)]
        root = repos[0].parent
    else:
        root = resolve_root(args.root)
        repos = find_repos(root)
    reports = await asyncio.gather(*(_repo_log(r, args.since, args.limit) for r in repos))
    return json.dumps(
        {"root": str(root), "since": args.since, "repos": [r for r in reports if r is not None]}
    )
