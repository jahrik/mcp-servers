from __future__ import annotations

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
async def test_gh_review_comments_list_reviewer_login_filter(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[
            {"id": 1, "body": "c1", "user": {"login": "octocat"}},
            {"id": 2, "body": "c2", "user": {"login": "Copilot"}},
        ],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(repo="octocat/repo", pr=1, reviewer_login="copilot")
    )
    data = [json.loads(line) for line in res.splitlines()]
    assert len(data) == 1
    assert data[0]["author"] == "Copilot"


@pytest.mark.asyncio
async def test_gh_review_comments_list_blank_reviewer_login_falls_back_to_bot_only(httpx_mock):
    """An explicit '' or whitespace reviewer_login must be treated as unset, not as a literal
    login that matches nothing — bot_only should still apply."""
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[
            {"id": 1, "body": "c1", "user": {"login": "octocat"}},
            {"id": 2, "body": "c2", "user": {"type": "Bot", "login": "bot"}},
        ],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(repo="octocat/repo", pr=1, bot_only=True, reviewer_login="   ")
    )
    data = [json.loads(line) for line in res.splitlines()]
    assert len(data) == 1
    assert data[0]["author"] == "bot"


@pytest.mark.asyncio
async def test_gh_review_comments_list_wait_for_completion(httpx_mock, monkeypatch):
    """Polls until a matching comment appears, sleeping between polls."""
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("mcp_servers.github.tools.reviews.asyncio.sleep", fake_sleep)

    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100", json=[]
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100",
        json=[{"id": 1, "body": "c1", "user": {"login": "octocat"}}],
    )
    res = await gh_review_comments_list(
        ReviewCommentsListArgs(
            repo="octocat/repo", pr=1, wait_for_completion=True, poll_interval_seconds=1
        )
    )
    data = [json.loads(line) for line in res.splitlines()]
    assert data[0]["id"] == 1
    assert sleeps == [1]


@pytest.mark.asyncio
async def test_gh_review_comments_list_wait_for_completion_timeout(httpx_mock, monkeypatch):
    fake_time = [0.0]

    def fake_monotonic():
        return fake_time[0]

    async def fake_sleep(seconds):
        fake_time[0] += seconds

    monkeypatch.setattr("mcp_servers.github.tools.reviews.time.monotonic", fake_monotonic)
    monkeypatch.setattr("mcp_servers.github.tools.reviews.asyncio.sleep", fake_sleep)

    for _ in range(2):
        httpx_mock.add_response(
            url="https://api.github.com/repos/octocat/repo/pulls/1/comments?per_page=100", json=[]
        )

    res = await gh_review_comments_list(
        ReviewCommentsListArgs(
            repo="octocat/repo",
            pr=1,
            wait_for_completion=True,
            timeout_seconds=2,
            poll_interval_seconds=1,
        )
    )
    assert res == ""


@pytest.mark.asyncio
async def test_gh_review_threads_get_reviewer_login_filter(httpx_mock):
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
                                },
                                {
                                    "comments": {
                                        "nodes": [
                                            {"author": {"__typename": "Bot", "login": "Copilot"}}
                                        ]
                                    }
                                },
                            ]
                        }
                    }
                }
            }
        },
    )
    res = await gh_review_threads_get(
        ReviewThreadsGetArgs(repo="octocat/repo", pr=1, reviewer_login="copilot")
    )
    nodes = json.loads(res)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_gh_review_threads_get_blank_reviewer_login_falls_back_to_bot_only(httpx_mock):
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
                                },
                                {
                                    "comments": {
                                        "nodes": [{"author": {"__typename": "Bot", "login": "bot"}}]
                                    }
                                },
                            ]
                        }
                    }
                }
            }
        },
    )
    res = await gh_review_threads_get(
        ReviewThreadsGetArgs(repo="octocat/repo", pr=1, bot_only=True, reviewer_login="  ")
    )
    nodes = json.loads(res)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    assert len(nodes) == 1


@pytest.mark.asyncio
async def test_gh_review_threads_get_wait_for_completion(httpx_mock, monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("mcp_servers.github.tools.reviews.asyncio.sleep", fake_sleep)

    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        json={"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": []}}}}},
    )
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        json={
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {"nodes": [{"id": "t1", "comments": {"nodes": []}}]}
                    }
                }
            }
        },
    )
    res = await gh_review_threads_get(
        ReviewThreadsGetArgs(
            repo="octocat/repo", pr=1, wait_for_completion=True, poll_interval_seconds=1
        )
    )
    nodes = json.loads(res)["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    assert len(nodes) == 1
    assert sleeps == [1]


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
