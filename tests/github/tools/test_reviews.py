import json

import pytest

from mcp_servers.github.models.schemas import (
    ReviewCommentReplyArgs,
    ReviewCommentsListArgs,
    ReviewThreadResolveArgs,
    ReviewThreadsGetArgs,
)
from mcp_servers.github.tools.reviews import (
    gh_review_comment_reply,
    gh_review_comments_list,
    gh_review_thread_resolve,
    gh_review_threads_get,
)


@pytest.fixture(autouse=True)
def mock_token(monkeypatch):
    import mcp_servers.github.client

    async def get_token():
        return "mock-token"

    monkeypatch.setattr(mcp_servers.github.client, "get_installation_token", get_token)


@pytest.mark.asyncio
async def test_gh_review_comments_list(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[
            {"id": 1, "body": "c1", "user": {"login": "octocat"}},
            {"id": 2, "user": {"type": "Bot", "login": "bot"}},
        ],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(repo="octocat/repo", pr=1, bot_only=True)
    )
    assert "bot" in res
    assert "octocat" not in res


@pytest.mark.asyncio
async def test_gh_review_threads_get(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        json={"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}},
    )
    res = await gh_review_threads_get(
        ReviewThreadsGetArgs(repo="octocat/repo", pr=1, bot_only=True)
    )
    assert "nodes" in res


@pytest.mark.asyncio
async def test_gh_review_comment_reply(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments/2/replies", json={"id": 3}
    )
    res = await gh_review_comment_reply(
        ReviewCommentReplyArgs(repo="octocat/repo", pr=1, comment_id=2, body="reply")
    )
    assert "3" in res
    with pytest.raises(ValueError):
        await gh_review_comment_reply(
            ReviewCommentReplyArgs(repo="octocat/repo", pr=1, comment_id=2, body="@reply")
        )


@pytest.mark.asyncio
async def test_gh_review_thread_resolve(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(url="https://api.github.com/graphql", json={"data": {}})
    res = await gh_review_thread_resolve(ReviewThreadResolveArgs(thread_id="thread1"))
    assert "{}" in res
    with pytest.raises(ValueError):
        await gh_review_thread_resolve(ReviewThreadResolveArgs(thread_id="@thread1"))


@pytest.mark.asyncio
async def test_gh_review_comments_list_nonbot(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[{"id": 1, "body": "c1", "user": {"login": "octocat"}}],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(repo="octocat/repo", pr=1, bot_only=True)
    )
    assert res == ""
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[{"id": 1, "body": "c1", "user": {"login": "octocat"}}],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(repo="octocat/repo", pr=1, bot_only=False)
    )
    assert "octocat" in res


@pytest.mark.asyncio
async def test_gh_review_threads_get_bot(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        json={
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "comments": {
                                        "nodes": [
                                            {"author": {"__typename": "User", "login": "octocat"}}
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        },
    )
    res = await gh_review_threads_get(
        ReviewThreadsGetArgs(repo="octocat/repo", pr=1, bot_only=True)
    )
    assert len(json.loads(res)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]) == 0


@pytest.mark.asyncio
async def test_gh_review_threads_get_bot_match(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        json={
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "comments": {
                                        "nodes": [
                                            {"author": {"__typename": "Bot", "login": "copilot"}}
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        },
    )
    res = await gh_review_threads_get(
        ReviewThreadsGetArgs(repo="octocat/repo", pr=1, bot_only=True)
    )
    assert len(json.loads(res)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]) == 1


@pytest.mark.asyncio
async def test_gh_review_comments_list_deleted_user(httpx_mock):
    """user: null from a deleted GitHub account must not crash; author should be empty string."""
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[{"id": 5, "body": "from deleted user", "user": None}],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(repo="octocat/repo", pr=1, bot_only=False)
    )
    data = [json.loads(line) for line in res.splitlines()]
    assert data[0]["id"] == 5
    assert data[0]["author"] == ""
