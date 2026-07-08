from __future__ import annotations

import json

import pytest

from mcp_servers.workspace.models.schemas import WsRepoArgs, WsStatusArgs
from mcp_servers.workspace.tools.status import ws_repo, ws_status


@pytest.mark.asyncio
async def test_ws_status_lists_repos(workspace):
    res = json.loads(await ws_status(WsStatusArgs(root=str(workspace))))
    assert res["root"] == str(workspace)
    assert [r["name"] for r in res["repos"]] == ["clean"]


@pytest.mark.asyncio
async def test_ws_status_attention_only(workspace, make_repo, add_origin):
    repo = make_repo(workspace, "tracked")
    add_origin(repo)
    (workspace / "clean" / "dirty.txt").write_text("x\n")
    res = json.loads(await ws_status(WsStatusArgs(root=str(workspace), attention_only=True)))
    # `tracked` is clean with an upstream — filtered out; `clean` is dirty + no upstream
    assert [r["name"] for r in res["repos"]] == ["clean"]


@pytest.mark.asyncio
async def test_ws_repo_detail(workspace, git, make_repo, add_origin):
    repo = make_repo(workspace, "detail")
    bare = add_origin(repo)
    git(repo, "branch", "feature")
    res = json.loads(await ws_repo(WsRepoArgs(path="detail", root=str(workspace))))
    assert res["path"] == str(repo)
    assert res["status"]["branch"] == "main"
    names = {b["name"]: b for b in res["branches"]}
    assert names["main"]["upstream"] == "origin/main"
    assert names["feature"]["upstream"] is None
    assert res["remotes"] == {"origin": str(bare)}
