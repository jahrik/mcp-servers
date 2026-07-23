from __future__ import annotations

import json

import pytest

from mcp_servers.github.models.schemas import MilestoneCreateArgs, MilestoneListArgs
from mcp_servers.github.tools.milestones import gh_milestone_create, gh_milestone_list


@pytest.mark.asyncio
async def test_gh_milestone_create(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="POST",
        url="https://api.github.com/repos/octocat/repo/milestones",
        json={"number": 1, "title": "v1.0", "state": "open"},
    )
    res = await gh_milestone_create(MilestoneCreateArgs(repo="octocat/repo", title="v1.0"))
    data = json.loads(res)
    assert data["number"] == 1
    assert data["title"] == "v1.0"
    sent = json.loads(httpx_mock.get_requests(method="POST")[0].content)
    assert sent == {"title": "v1.0"}


@pytest.mark.asyncio
async def test_gh_milestone_create_with_optional_fields(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="POST",
        url="https://api.github.com/repos/octocat/repo/milestones",
        json={"number": 2, "title": "v2.0"},
    )
    res = await gh_milestone_create(
        MilestoneCreateArgs(
            repo="octocat/repo",
            title="v2.0",
            description="second release",
            due_on="2026-12-31T00:00:00Z",
        )
    )
    assert json.loads(res)["number"] == 2
    sent = json.loads(httpx_mock.get_requests(method="POST")[0].content)
    assert sent == {
        "title": "v2.0",
        "description": "second release",
        "due_on": "2026-12-31T00:00:00Z",
    }


@pytest.mark.asyncio
async def test_gh_milestone_list(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/milestones?state=open",
        json=[
            {
                "number": 1,
                "title": "v1.0",
                "state": "open",
                "open_issues": 3,
                "closed_issues": 1,
            }
        ],
    )
    res = await gh_milestone_list(MilestoneListArgs(repo="octocat/repo"))
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["number"] == 1
    assert data[0]["openIssues"] == 3
