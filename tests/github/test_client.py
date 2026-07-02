import pytest

from mcp_servers.github.client import (
    GhError,
    get_installation_token,
    gh_request,
    gh_request_paginated,
    validate_ref,
    validate_repo,
)


@pytest.mark.asyncio
async def test_get_installation_token(httpx_mock, monkeypatch):
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "456")
    import mcp_servers.github.client

    monkeypatch.setattr(mcp_servers.github.client, "get_jwt", lambda: "mock-jwt")

    httpx_mock.add_response(
        url="https://api.github.com/app/installations/456/access_tokens",
        json={"token": "mock-token"},
    )
    mcp_servers.github.client._TOKEN_CACHE.clear()

    token = await get_installation_token()
    assert token == "mock-token"
    # Cached
    token = await get_installation_token()
    assert token == "mock-token"


@pytest.mark.asyncio
async def test_get_installation_token_missing_env(monkeypatch):
    monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
    with pytest.raises(RuntimeError):
        await get_installation_token()


@pytest.mark.asyncio
async def test_gh_request(httpx_mock, monkeypatch):
    import mcp_servers.github.client

    async def mock_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", mock_token)

    httpx_mock.add_response(url="https://api.github.com/repos/owner/repo", json={"id": 1})
    resp = await gh_request("GET", "repos/owner/repo")
    assert resp.json() == {"id": 1}

    httpx_mock.add_response(url="https://api.github.com/graphql", json={"data": {}})
    resp = await gh_request("POST", "https://api.github.com/graphql")
    assert resp.json() == {"data": {}}


@pytest.mark.asyncio
async def test_gh_request_follows_redirects(httpx_mock, monkeypatch):
    """Job-log downloads 302 to blob storage — gh_request must follow that."""
    import mcp_servers.github.client

    async def mock_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", mock_token)

    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo/actions/jobs/1/logs",
        status_code=302,
        headers={"Location": "https://blob.example.com/logs.txt"},
    )
    httpx_mock.add_response(url="https://blob.example.com/logs.txt", text="log output")

    resp = await gh_request("GET", "repos/owner/repo/actions/jobs/1/logs")
    assert resp.text == "log output"


@pytest.mark.asyncio
async def test_gh_request_error(httpx_mock, monkeypatch):
    import mcp_servers.github.client

    async def mock_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", mock_token)

    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo", status_code=404, text="Not Found"
    )
    with pytest.raises(GhError):
        await gh_request("GET", "repos/owner/repo")

    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo2", status_code=422, text="Unprocessable"
    )
    with pytest.raises(GhError):
        await gh_request("GET", "repos/owner/repo2")


@pytest.mark.asyncio
async def test_gh_request_paginated_follows_link_header(httpx_mock, monkeypatch):
    import mcp_servers.github.client

    async def mock_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", mock_token)

    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo/pulls/1/comments?per_page=100",
        json=[{"id": 1}],
        headers={
            "Link": '<https://api.github.com/repos/owner/repo/pulls/1/comments?page=2>; rel="next"'
        },
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo/pulls/1/comments?page=2",
        json=[{"id": 2}],
    )

    results = await gh_request_paginated("GET", "repos/owner/repo/pulls/1/comments")
    assert [r["id"] for r in results] == [1, 2]


@pytest.mark.asyncio
async def test_gh_request_paginated_respects_max_items(httpx_mock, monkeypatch):
    import mcp_servers.github.client

    async def mock_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", mock_token)

    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo/pulls/1/comments?per_page=100",
        json=[{"id": 1}, {"id": 2}, {"id": 3}],
    )

    results = await gh_request_paginated("GET", "repos/owner/repo/pulls/1/comments", max_items=2)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_gh_request_paginated_non_list_response(httpx_mock, monkeypatch):
    import mcp_servers.github.client

    async def mock_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", mock_token)

    httpx_mock.add_response(
        url="https://api.github.com/repos/owner/repo?per_page=100",
        json={"id": 1},
    )
    result = await gh_request_paginated("GET", "repos/owner/repo")
    assert result == {"id": 1}


def test_validate_repo():
    assert validate_repo("owner/repo") == "owner/repo"
    with pytest.raises(GhError):
        validate_repo("invalid")


def test_validate_ref():
    assert validate_ref("main") == "main"
    with pytest.raises(GhError):
        validate_ref("-invalid")
