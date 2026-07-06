import json

import pytest

from mcp_servers.workspace.git import WsError
from mcp_servers.workspace.models.schemas import WsLogArgs
from mcp_servers.workspace.tools.log import ws_log


@pytest.mark.asyncio
async def test_ws_log_reports_recent_commits(workspace):
    res = json.loads(await ws_log(WsLogArgs(root=str(workspace))))
    assert res["since"] == "1 week"
    (repo,) = res["repos"]
    assert repo["name"] == "clean"
    (commit,) = repo["commits"]
    assert commit["subject"] == "init"
    assert isinstance(commit["author"], str)
    assert commit["sha"]
    assert commit["date"]


@pytest.mark.asyncio
async def test_ws_log_omits_repos_with_no_matching_commits(workspace):
    # NB: keep the future date near-term — git approxidate silently misparses
    # far-future years (e.g. 2999) as "now" instead of erroring.
    res = json.loads(await ws_log(WsLogArgs(root=str(workspace), since="2030-01-01")))
    assert res["repos"] == []


@pytest.mark.asyncio
async def test_ws_log_includes_commits_from_other_branches(workspace, git, make_repo):
    repo = make_repo(workspace, "branched")
    git(repo, "checkout", "-b", "feature")
    (repo / "f.txt").write_text("x\n")
    git(repo, "add", "f.txt")
    git(repo, "commit", "-m", "feature work")
    git(repo, "checkout", "main")

    res = json.loads(await ws_log(WsLogArgs(root=str(workspace), path="branched")))
    (report,) = res["repos"]
    assert [c["subject"] for c in report["commits"]] == ["feature work", "init"]


@pytest.mark.asyncio
async def test_ws_log_limit_caps_commits_per_repo(workspace, git):
    repo = workspace / "clean"
    for i in range(3):
        (repo / f"f{i}.txt").write_text("x\n")
        git(repo, "add", f"f{i}.txt")
        git(repo, "commit", "-m", f"change {i}")

    res = json.loads(await ws_log(WsLogArgs(root=str(workspace), limit=2)))
    (report,) = res["repos"]
    assert [c["subject"] for c in report["commits"]] == ["change 2", "change 1"]


@pytest.mark.asyncio
async def test_ws_log_single_path_form(workspace):
    res = json.loads(await ws_log(WsLogArgs(path=str(workspace / "clean"))))
    assert res["root"] == str(workspace)
    assert res["repos"][0]["name"] == "clean"


@pytest.mark.asyncio
async def test_ws_log_rejects_flag_like_since(workspace):
    with pytest.raises(WsError, match="not a flag"):
        await ws_log(WsLogArgs(root=str(workspace), since="--output=/tmp/evil"))
