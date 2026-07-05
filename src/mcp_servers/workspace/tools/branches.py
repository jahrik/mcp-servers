from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..git import WsError, find_repos, resolve_root, run_git
from ..models.schemas import WsBranchesArgs


async def _default_branch(repo: Path) -> str | None:
    """The branch origin/HEAD points at, if the repo has one recorded."""
    try:
        ref = await run_git(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    except WsError:
        return None
    return ref.strip().removeprefix("origin/")


async def _repo_branches(repo: Path) -> dict[str, object] | None:
    refs = await run_git(
        repo,
        "for-each-ref",
        "refs/heads",
        "--format=%(refname:short)\t%(upstream:short)\t%(upstream:track)",
    )
    default = await _default_branch(repo)
    merged: set[str] = set()
    if default:
        merged_out = await run_git(repo, "branch", "--merged", default, "--format=%(refname:short)")
        merged = {b for b in merged_out.splitlines() if b and b != default}
    gone, local_only, merged_branches = [], [], []
    for line in refs.splitlines():
        name, upstream, track = line.split("\t")
        if name == default:
            continue
        if track == "[gone]":
            gone.append(name)
        elif not upstream and default:
            # without a recorded default branch there is no baseline to call a
            # branch "stale" against — ws_status already flags missing upstreams
            local_only.append(name)
        if name in merged:
            merged_branches.append(name)
    if not (gone or local_only or merged_branches):
        return None
    return {
        "name": repo.name,
        "default_branch": default,
        "gone_upstream": gone,
        "local_only": local_only,
        "merged_into_default": merged_branches,
    }


async def ws_branches(args: WsBranchesArgs) -> str:
    """Stale-branch report across the workspace: branches whose upstream is gone,
    local-only branches, and branches already merged into the default branch.
    Repos with nothing to report are omitted.

    Args:
        root: Workspace root to scan. Defaults to $MCP_WORKSPACE_ROOT, then ~/github.
    """
    root = resolve_root(args.root)
    reports = await asyncio.gather(*(_repo_branches(repo) for repo in find_repos(root)))
    return json.dumps({"root": str(root), "repos": [r for r in reports if r is not None]})
