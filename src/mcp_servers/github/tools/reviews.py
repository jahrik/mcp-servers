from __future__ import annotations

import asyncio
import json
import time

from mcp_servers.github.client import gh_request, gh_request_paginated, validate_repo

from ..models.schemas import (
    ReviewCommentReplyArgs,
    ReviewCommentsListArgs,
    ReviewThreadResolveArgs,
    ReviewThreadsGetArgs,
)
from ..utils import _audit_log

_THREADS_QUERY = """
query($owner:String!,$name:String!,$pr:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$pr){
      reviewThreads(first:100){
        nodes{
          id
          isResolved
          isOutdated
          comments(first:100){
            nodes{ databaseId author{login __typename} path line body }
          }
        }
      }
    }
  }
}
"""

_RESOLVE_MUTATION = """
mutation($threadId:ID!){
  resolveReviewThread(input:{threadId:$threadId}){ thread{ id isResolved } }
}
"""


async def _fetch_review_comments(
    repo: str, pr: int, bot_only: bool, reviewer_login: str | None
) -> list[dict]:
    comments = await gh_request_paginated("GET", f"repos/{repo}/pulls/{int(pr)}/comments")

    results = []
    for c in comments:
        user = c.get("user") or {}
        login = user.get("login", "")
        if reviewer_login:
            if login.lower() != reviewer_login.lower():
                continue
        elif bot_only:
            is_bot = user.get("type") == "Bot" or "copilot" in login.lower()
            if not is_bot:
                continue
        results.append(
            {
                "id": c.get("id"),
                "author": login,
                "path": c.get("path"),
                "line": c.get("line") or c.get("original_line"),
                "body": c.get("body"),
            }
        )
    return results


async def gh_review_comments_list(args: ReviewCommentsListArgs) -> str:
    """List a PR's inline review comments (read-only).

    With ``wait_for_completion=True``, polls in-process until at least one
    matching comment appears or ``timeout_seconds`` elapses, mirroring
    ``gh_run_get``'s poll pattern — so waiting for a review doesn't require
    looping calls across separate turns.
    """
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    reviewer_login = args.reviewer_login
    validate_repo(repo)

    results = await _fetch_review_comments(repo, pr, bot_only, reviewer_login)
    if args.wait_for_completion:
        deadline = time.monotonic() + args.timeout_seconds
        while not results:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(args.poll_interval_seconds, remaining))
            if time.monotonic() >= deadline:
                break
            results = await _fetch_review_comments(repo, pr, bot_only, reviewer_login)

    return "\n".join(json.dumps(r) for r in results)


def _keep_thread(node: dict, bot_only: bool, reviewer_login: str | None) -> bool:
    for c in node.get("comments", {}).get("nodes", []):
        author = c.get("author", {}) or {}
        login = author.get("login", "")
        if reviewer_login:
            if login.lower() == reviewer_login.lower():
                return True
        elif bot_only and (author.get("__typename") == "Bot" or "copilot" in login.lower()):
            return True
    return False


async def _fetch_review_threads(
    repo: str, pr: int, bot_only: bool, reviewer_login: str | None
) -> tuple[dict, list[dict]]:
    owner, _, name = repo.partition("/")
    payload = {"query": _THREADS_QUERY, "variables": {"owner": owner, "name": name, "pr": int(pr)}}
    resp = await gh_request("POST", "graphql", json=payload)
    data = resp.json()

    thread_data = ((data.get("data") or {}).get("repository") or {}).get("pullRequest") or {}
    review_threads = thread_data.get("reviewThreads") or {}
    nodes = review_threads.get("nodes") or []

    if (bot_only or reviewer_login) and "nodes" in review_threads:
        nodes = [n for n in nodes if _keep_thread(n, bot_only, reviewer_login)]
        review_threads["nodes"] = nodes

    return data, nodes


async def gh_review_threads_get(args: ReviewThreadsGetArgs) -> str:
    """List a PR's review threads with ids and resolved state (read-only).

    With ``wait_for_completion=True``, polls in-process until at least one
    matching thread appears or ``timeout_seconds`` elapses, mirroring
    ``gh_run_get``'s poll pattern — so waiting for a review doesn't require
    looping calls across separate turns.
    """
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    reviewer_login = args.reviewer_login
    validate_repo(repo)

    data, nodes = await _fetch_review_threads(repo, pr, bot_only, reviewer_login)
    if args.wait_for_completion:
        deadline = time.monotonic() + args.timeout_seconds
        while not nodes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(args.poll_interval_seconds, remaining))
            if time.monotonic() >= deadline:
                break
            data, nodes = await _fetch_review_threads(repo, pr, bot_only, reviewer_login)

    return json.dumps(data)


@_audit_log
async def gh_review_comment_reply(args: ReviewCommentReplyArgs) -> str:
    """Reply to a PR inline review comment's thread (write)."""
    repo = args.repo
    pr = args.pr
    comment_id = args.comment_id
    body = args.body
    if body.lstrip().startswith("@"):
        raise ValueError("Body cannot start with '@'")
    validate_repo(repo)
    resp = await gh_request(
        "POST",
        f"repos/{repo}/pulls/{int(pr)}/comments/{int(comment_id)}/replies",
        json={"body": body},
    )
    return json.dumps(resp.json())


@_audit_log
async def gh_review_thread_resolve(args: ReviewThreadResolveArgs) -> str:
    """Resolve a PR review thread by its node id (write)."""
    thread_id = args.thread_id
    if thread_id.lstrip().startswith("@"):
        raise ValueError("Thread ID cannot start with '@'")

    payload = {"query": _RESOLVE_MUTATION, "variables": {"threadId": thread_id}}
    resp = await gh_request("POST", "graphql", json=payload)
    return json.dumps(resp.json())
