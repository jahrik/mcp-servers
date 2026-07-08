from __future__ import annotations

import json

import pytest

from mcp_servers.github.models.schemas import (
    ApiGetArgs,
    ApiGraphqlArgs,
    FileGetArgs,
    SearchCodeArgs,
    SearchIssuesArgs,
    SearchPrsArgs,
)
from mcp_servers.github.tools.api import (
    gh_api_get,
    gh_api_graphql,
    gh_file_get,
    gh_search_code,
    gh_search_issues,
    gh_search_prs,
)


@pytest.mark.asyncio
async def test_gh_file_get(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/contents/README.md?ref=main", text="hello"
    )
    res = await gh_file_get(FileGetArgs(repo="octocat/repo", path="README.md", ref="main"))
    assert res == "hello"


@pytest.mark.asyncio
async def test_gh_search_code(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/search/code?q=foo+repo:octocat/repo&per_page=10",
        json={"items": [{"name": "foo.py"}]},
    )
    res = await gh_search_code(SearchCodeArgs(query="foo", repo="octocat/repo", limit=10))
    assert "foo.py" in res


@pytest.mark.asyncio
async def test_gh_search_prs(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/search/issues?q=foo+repo:octocat/repo+is:pr&per_page=10",
        json={"items": [{"number": 1}]},
    )
    res = await gh_search_prs(SearchPrsArgs(query="foo", repo="octocat/repo", limit=10))
    assert json.loads(res)[0]["number"] == 1


@pytest.mark.asyncio
async def test_gh_search_issues(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/search/issues?q=foo+repo:octocat/repo+is:issue&per_page=10",
        json={"items": [{"number": 2}]},
    )
    res = await gh_search_issues(SearchIssuesArgs(query="foo", repo="octocat/repo", limit=10))
    assert json.loads(res)[0]["number"] == 2


@pytest.mark.asyncio
async def test_gh_api_get(httpx_mock, monkeypatch):
    httpx_mock.add_response(url="https://api.github.com/user", text='{"login": "octocat"}')
    res = await gh_api_get(ApiGetArgs(endpoint="user"))
    assert "octocat" in res


@pytest.mark.asyncio
async def test_gh_api_get_jq(httpx_mock):
    httpx_mock.add_response(url="https://api.github.com/user", text='{"login": "octocat"}')
    res = await gh_api_get(ApiGetArgs(endpoint="user", jq_filter=".login"))
    assert res == "octocat"


@pytest.mark.asyncio
async def test_gh_api_get_jq_invalid_filter(httpx_mock):
    httpx_mock.add_response(url="https://api.github.com/user", text='{"login": "octocat"}')
    with pytest.raises(ValueError, match="Invalid jq filter"):
        await gh_api_get(ApiGetArgs(endpoint="user", jq_filter="not valid jq ("))


@pytest.mark.asyncio
async def test_gh_api_get_graphql_error():
    with pytest.raises(ValueError):
        await gh_api_get(ApiGetArgs(endpoint="graphql"))


@pytest.mark.asyncio
async def test_gh_api_graphql(httpx_mock, monkeypatch):
    httpx_mock.add_response(
        url="https://api.github.com/graphql", text='{"data": {"viewer": {"login": "octocat"}}}'
    )
    res = await gh_api_graphql(ApiGraphqlArgs(query="query { viewer { login } }"))
    assert "octocat" in res


@pytest.mark.asyncio
async def test_gh_api_graphql_errors():
    with pytest.raises(ValueError):
        await gh_api_graphql(ApiGraphqlArgs(query="@query"))
    with pytest.raises(ValueError):
        await gh_api_graphql(ApiGraphqlArgs(query="mutation { foo }"))


@pytest.mark.asyncio
async def test_gh_api_get_jq_not_json(httpx_mock):
    httpx_mock.add_response(url="https://api.github.com/user", text="not json")
    with pytest.raises(ValueError, match="not valid JSON"):
        await gh_api_get(ApiGetArgs(endpoint="user", jq_filter=".login"))


@pytest.mark.asyncio
async def test_gh_api_graphql_jq(httpx_mock):
    httpx_mock.add_response(url="https://api.github.com/graphql", text='{"data": {"a": 1}}')
    res = await gh_api_graphql(ApiGraphqlArgs(query="query { }", jq_filter=".data.a"))
    assert res == "1"


@pytest.mark.asyncio
async def test_gh_api_graphql_with_vars(httpx_mock):
    httpx_mock.add_response(url="https://api.github.com/graphql", text='{"data": {}}')
    res = await gh_api_graphql(ApiGraphqlArgs(query="query { }", variables={"a": "b"}))
    assert res == '{"data": {}}'
