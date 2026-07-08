from __future__ import annotations

import json

import pytest

from mcp_servers.github.client import GhError
from mcp_servers.github.models.schemas import RepoGetArgs, RepoListArgs
from mcp_servers.github.tools.repos import gh_repo_get, gh_repo_list


@pytest.mark.asyncio
async def test_gh_repo_list_org(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/orgs/octocat/repos?per_page=10&sort=pushed",
        json=[{"name": "repo1", "full_name": "octocat/repo1", "description": "desc"}],
    )
    res = await gh_repo_list(RepoListArgs(owner="octocat", limit=10))
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["name"] == "repo1"


@pytest.mark.asyncio
async def test_gh_repo_list_falls_back_to_user(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/orgs/octocat/repos?per_page=10&sort=pushed",
        status_code=404,
        text="Not Found",
    )
    httpx_mock.add_response(
        url="https://api.github.com/users/octocat/repos?per_page=10&sort=pushed",
        json=[{"name": "repo1", "full_name": "octocat/repo1", "description": "desc"}],
    )
    res = await gh_repo_list(RepoListArgs(owner="octocat", limit=10, no_cache=True))
    data = json.loads(res)
    assert len(data) == 1
    assert data[0]["name"] == "repo1"


@pytest.mark.asyncio
async def test_gh_repo_list_reraises_non_404(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/orgs/octocat/repos?per_page=10&sort=pushed",
        status_code=500,
        text="Internal Server Error",
    )
    with pytest.raises(GhError, match="500"):
        await gh_repo_list(RepoListArgs(owner="octocat", limit=10, no_cache=True))


@pytest.mark.asyncio
async def test_gh_repo_get(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo1",
        json={"name": "repo1", "full_name": "octocat/repo1", "language": "Python"},
    )
    res = await gh_repo_get(RepoGetArgs(repo="octocat/repo1"))
    data = json.loads(res)
    assert data["name"] == "repo1"
