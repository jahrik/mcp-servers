import json

import pytest

from mcp_servers.github.models.schemas import (
    PrArgs,
    PrCommentArgs,
    PrCreateArgs,
    PrEditArgs,
    PrListArgs,
    PrMergeArgs,
    PrRequestReviewersArgs,
)
from mcp_servers.github.tools.prs import (
    _check_bucket,
    gh_pr_checks,
    gh_pr_comment,
    gh_pr_create,
    gh_pr_diff,
    gh_pr_edit,
    gh_pr_get,
    gh_pr_list,
    gh_pr_merge,
    gh_pr_request_reviewers,
)


@pytest.mark.parametrize(
    ("status", "conclusion", "expected"),
    [
        ("in_progress", None, "pending"),
        ("completed", "cancelled", "cancel"),
        ("completed", "skipped", "skipping"),
        ("completed", "success", "pass"),
        ("completed", "neutral", "pass"),
        ("completed", "failure", "fail"),
    ],
)
def test_check_bucket(status, conclusion, expected):
    assert _check_bucket(status, conclusion) == expected


@pytest.fixture(autouse=True)
def mock_token(monkeypatch):
    import mcp_servers.github.client

    async def get_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", get_token)


@pytest.mark.asyncio
async def test_gh_pr_list(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls?state=open&per_page=10",
        json=[{"number": 1, "title": "pr 1", "head": {"ref": "feature"}}],
    )
    res = await gh_pr_list(PrListArgs(repo="octocat/repo", state="open", limit=10))
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["number"] == 1


@pytest.mark.asyncio
async def test_gh_pr_get(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1", json={"number": 1}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/files",
        json=[{"filename": "a.txt", "additions": 1, "deletions": 0}],
    )
    res = await gh_pr_get(PrArgs(repo="octocat/repo", number=1))
    data = json.loads(res)
    assert data["number"] == 1
    assert len(data["files"]) == 1


@pytest.mark.asyncio
async def test_gh_pr_diff(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1", text="diff --git a/a.txt b/a.txt"
    )
    res = await gh_pr_diff(PrArgs(repo="octocat/repo", number=1))
    assert res.startswith("diff")


@pytest.mark.asyncio
async def test_gh_pr_checks(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1", json={"head": {"sha": "abcdef"}}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/commits/abcdef/check-runs",
        json={"check_runs": [{"name": "test", "status": "completed", "conclusion": "success"}]},
    )
    res = await gh_pr_checks(PrArgs(repo="octocat/repo", number=1))
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["state"] == "success"
    assert data[0]["bucket"] == "pass"


@pytest.mark.asyncio
async def test_gh_pr_create(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls", json={"number": 2}
    )
    res = await gh_pr_create(
        PrCreateArgs(
            repo="octocat/repo",
            title="new pr",
            body="desc",
            head="feature",
            base="main",
            draft=False,
        )
    )
    assert json.loads(res)["number"] == 2


@pytest.mark.asyncio
async def test_gh_pr_edit(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1", json={"number": 1}
    )
    res = await gh_pr_edit(PrEditArgs(repo="octocat/repo", pr=1, title="new title"))
    assert json.loads(res)["number"] == 1


@pytest.mark.asyncio
async def test_gh_pr_comment(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues/1/comments", json={"id": 3}
    )
    res = await gh_pr_comment(PrCommentArgs(repo="octocat/repo", pr=1, body="comment"))
    assert json.loads(res)["id"] == 3


@pytest.mark.asyncio
async def test_gh_pr_merge(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1", json={"head": {"ref": "feature"}}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/merge", json={"merged": True}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/git/refs/heads/feature", json={}
    )
    res = await gh_pr_merge(
        PrMergeArgs(
            repo="octocat/repo", pr=1, merge_method="squash", delete_branch=True, confirm=True
        )
    )
    assert json.loads(res)["merged"] is True


@pytest.mark.asyncio
async def test_gh_pr_merge_branch_delete_failure_surfaces(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1", json={"head": {"ref": "feature"}}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/merge", json={"merged": True}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/git/refs/heads/feature",
        status_code=422,
        text="Reference does not exist",
    )
    res = await gh_pr_merge(
        PrMergeArgs(
            repo="octocat/repo", pr=1, merge_method="squash", delete_branch=True, confirm=True
        )
    )
    data = json.loads(res)
    assert data["merged"] is True
    assert "branch_delete_error" in data


@pytest.mark.asyncio
async def test_gh_pr_merge_no_confirm(monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    with pytest.raises(ValueError):
        await gh_pr_merge(PrMergeArgs(repo="octocat/repo", pr=1, confirm=False))


@pytest.mark.asyncio
async def test_gh_pr_checks_missing_sha(httpx_mock):
    """If the PR head SHA is absent, gh_pr_checks must raise a descriptive GhError."""
    from mcp_servers.github.client import GhError

    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1",
        json={"head": {}},  # no sha key
    )
    with pytest.raises(GhError, match="PR head SHA unavailable"):
        await gh_pr_checks(PrArgs(repo="octocat/repo", number=1))


@pytest.mark.asyncio
async def test_gh_pr_request_reviewers(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/requested_reviewers",
        json={"requested_reviewers": [{"login": "user1"}]},
    )
    res = await gh_pr_request_reviewers(
        PrRequestReviewersArgs(
            repo="octocat/repo",
            pr=1,
            reviewers=["user1"],
        )
    )
    data = json.loads(res)
    assert data["requested_reviewers"][0]["login"] == "user1"


@pytest.mark.asyncio
async def test_gh_pr_request_reviewers_team(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/requested_reviewers",
        json={"requested_teams": [{"slug": "justice-league"}]},
    )
    res = await gh_pr_request_reviewers(
        PrRequestReviewersArgs(
            repo="octocat/repo",
            pr=1,
            team_reviewers=["justice-league"],
        )
    )
    data = json.loads(res)
    assert data["requested_teams"][0]["slug"] == "justice-league"


@pytest.mark.asyncio
async def test_gh_pr_request_reviewers_validation_error(monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    with pytest.raises(ValueError, match="Must provide either reviewers or team_reviewers"):
        await gh_pr_request_reviewers(
            PrRequestReviewersArgs(
                repo="octocat/repo",
                pr=1,
            )
        )
