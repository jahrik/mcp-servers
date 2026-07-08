from __future__ import annotations

import json

import pytest

from mcp_servers.workspace.models.schemas import WsBranchesArgs
from mcp_servers.workspace.tools.branches import ws_branches


@pytest.mark.asyncio
async def test_ws_branches_clean_workspace_is_empty(workspace):
    # `clean` has only main and no origin/HEAD — nothing to report
    res = json.loads(await ws_branches(WsBranchesArgs(root=str(workspace))))
    assert res["repos"] == []


@pytest.mark.asyncio
async def test_ws_branches_classifies_stale_branches(workspace, git, make_repo, add_origin):
    repo = make_repo(workspace, "stale")
    add_origin(repo)

    # merged into default: branched off main with no extra commits
    git(repo, "branch", "merged-work")

    # local-only with its own commit (not merged)
    git(repo, "checkout", "-b", "local-work")
    (repo / "local.txt").write_text("x\n")
    git(repo, "add", "local.txt")
    git(repo, "commit", "-m", "local work")

    # gone upstream: pushed with tracking, then deleted on the remote
    git(repo, "checkout", "-b", "gone-work")
    (repo / "gone.txt").write_text("x\n")
    git(repo, "add", "gone.txt")
    git(repo, "commit", "-m", "gone work")
    git(repo, "push", "-u", "origin", "gone-work")
    git(repo, "push", "origin", "--delete", "gone-work")
    git(repo, "fetch", "--prune")
    git(repo, "checkout", "main")

    res = json.loads(await ws_branches(WsBranchesArgs(root=str(workspace))))
    assert [r["name"] for r in res["repos"]] == ["stale"]
    report = res["repos"][0]
    assert report["default_branch"] == "main"
    assert report["gone_upstream"] == ["gone-work"]
    assert report["local_only"] == ["local-work", "merged-work"]
    assert report["merged_into_default"] == ["merged-work"]
