from __future__ import annotations

import json

import pytest

from mcp_servers.github.models.schemas import (
    IssueArgs,
    IssueCommentArgs,
    IssueCreateArgs,
    IssueEditArgs,
    IssueListArgs,
)
from mcp_servers.github.tools.issues import (
    gh_issue_comment,
    gh_issue_create,
    gh_issue_edit,
    gh_issue_get,
    gh_issue_list,
)


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
async def test_gh_issue_edit_close(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="PATCH",
        url="https://api.github.com/repos/octocat/repo/issues/1",
        json={"number": 1, "state": "closed"},
    )
    res = await gh_issue_edit(
        IssueEditArgs(repo="octocat/repo", number=1, state="closed", state_reason="completed")
    )
    assert json.loads(res)["state"] == "closed"
    sent = json.loads(httpx_mock.get_requests(method="PATCH")[0].content)
    assert sent == {"state": "closed", "state_reason": "completed"}


@pytest.mark.asyncio
async def test_gh_issue_edit_metadata(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="PATCH",
        url="https://api.github.com/repos/octocat/repo/issues/2",
        json={"number": 2},
    )
    res = await gh_issue_edit(
        IssueEditArgs(
            repo="octocat/repo", number=2, title="new title", body="new body", labels=["bug"]
        )
    )
    assert json.loads(res)["number"] == 2
    sent = json.loads(httpx_mock.get_requests(method="PATCH")[0].content)
    assert sent == {"title": "new title", "body": "new body", "labels": ["bug"]}


@pytest.mark.asyncio
async def test_gh_issue_edit_milestone(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="PATCH",
        url="https://api.github.com/repos/octocat/repo/issues/1",
        json={"number": 1, "milestone": {"number": 3}},
    )
    res = await gh_issue_edit(IssueEditArgs(repo="octocat/repo", number=1, milestone=3))
    assert json.loads(res)["number"] == 1
    sent = json.loads(httpx_mock.get_requests(method="PATCH")[0].content)
    assert sent == {"milestone": 3}


@pytest.mark.asyncio
async def test_gh_issue_edit_milestone_clear(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="PATCH",
        url="https://api.github.com/repos/octocat/repo/issues/1",
        json={"number": 1, "milestone": None},
    )
    res = await gh_issue_edit(IssueEditArgs(repo="octocat/repo", number=1, milestone="clear"))
    assert json.loads(res)["number"] == 1
    sent = json.loads(httpx_mock.get_requests(method="PATCH")[0].content)
    assert sent == {"milestone": None}


def test_issue_edit_args_requires_a_field():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="at least one field"):
        IssueEditArgs(repo="octocat/repo", number=1)


def test_issue_edit_args_rejects_mismatched_state_reason():
    from pydantic import ValidationError

    # completed pairs with closed, not open
    with pytest.raises(ValidationError, match="requires state='closed'"):
        IssueEditArgs(repo="octocat/repo", number=1, state="open", state_reason="completed")
    # state_reason with no state at all is also a mismatch
    with pytest.raises(ValidationError, match="requires state='open'"):
        IssueEditArgs(repo="octocat/repo", number=1, state_reason="reopened")


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
