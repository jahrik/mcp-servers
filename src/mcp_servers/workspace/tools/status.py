from __future__ import annotations

import asyncio
import json

from ..git import find_repos, needs_attention, repo_status, resolve_repo, resolve_root, run_git
from ..models.schemas import WsRepoArgs, WsStatusArgs


async def ws_status(args: WsStatusArgs) -> str:
    """Status of every git repo in the workspace root (one directory level deep).

    Args:
        root: Workspace root to scan. Defaults to $MCP_WORKSPACE_ROOT, then ~/github.
        attention_only: Only return repos needing attention (dirty tree,
            ahead/behind upstream, stashes, or no upstream).
    """
    root = resolve_root(args.root)
    statuses = await asyncio.gather(*(repo_status(repo) for repo in find_repos(root)))
    results = [s for s in statuses if not args.attention_only or needs_attention(s)]
    return json.dumps({"root": str(root), "repos": results})


async def ws_repo(args: WsRepoArgs) -> str:
    """Detailed view of one repo: status, local branches with tracking, remotes.

    Args:
        path: Repo path — absolute, ``~``-relative, or relative to the workspace root.
        root: Workspace root used to resolve a relative ``path``.
    """
    repo = resolve_repo(args.path, args.root)
    status = await repo_status(repo)
    refs = await run_git(
        repo,
        "for-each-ref",
        "refs/heads",
        "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)",
    )
    branches = []
    for line in refs.splitlines():
        name, upstream, track = line.split("\t")
        branches.append(
            {
                "name": name,
                "upstream": upstream or None,
                "track": track or None,
            }
        )
    remotes_out = await run_git(repo, "remote", "-v")
    remotes = {}
    for line in remotes_out.splitlines():
        name, url = line.split("\t")[0], line.split("\t")[1].split(" ")[0]
        remotes[name] = url
    return json.dumps(
        {"path": str(repo), "status": status, "branches": branches, "remotes": remotes}
    )
