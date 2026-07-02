import json

import pytest

from mcp_servers.github.models.schemas import (
    IssueArgs,
    IssueCommentArgs,
    IssueCreateArgs,
    IssueListArgs,
)
from mcp_servers.github.tools.issues import (
    gh_issue_comment,
    gh_issue_create,
    gh_issue_get,
    gh_issue_list,
)


@pytest.fixture(autouse=True)
def mock_token(monkeypatch):
    import mcp_servers.github.client

    async def get_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", get_token)


@pytest.mark.asyncio
async def test_gh_issue_list(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues?state=open&per_page=10",
        json=[
            {"number": 1, "title": "issue 1", "labels": [{"name": "bug"}]},
            {"number": 2, "pull_request": {}},
        ],
    )
    res = await gh_issue_list(IssueListArgs(repo="octocat/repo", state="open", limit=10))
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["number"] == 1
    assert data[0]["labels"][0]["name"] == "bug"


@pytest.mark.asyncio
async def test_gh_issue_get(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues/1",
        json={"number": 1, "title": "issue 1"},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues/1/comments",
        json=[{"body": "c1", "user": {"login": "octocat"}}],
    )
    res = await gh_issue_get(IssueArgs(repo="octocat/repo", number=1))
    data = json.loads(res)
    assert data["number"] == 1
    assert len(data["comments"]) == 1


@pytest.mark.asyncio
async def test_gh_issue_create(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues", json={"number": 2}
    )
    res = await gh_issue_create(IssueCreateArgs(repo="octocat/repo", title="new", body="body"))
    assert json.loads(res)["number"] == 2


@pytest.mark.asyncio
async def test_gh_issue_comment(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues/1/comments", json={"id": 3}
    )
    res = await gh_issue_comment(IssueCommentArgs(repo="octocat/repo", issue=1, body="comment"))
    assert json.loads(res)["id"] == 3


@pytest.mark.asyncio
async def test_gh_issue_get_empty_author(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues/1",
        json={"number": 1, "title": "issue 1", "user": None},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/issues/1/comments",
        json=[{"body": "c1", "user": None}],
    )
    res = await gh_issue_get(IssueArgs(repo="octocat/repo", number=1))
    data = json.loads(res)
    assert data["author"] == {}
    assert data["comments"][0]["author"] == {}
