from __future__ import annotations

import json

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


async def gh_review_comments_list(args: ReviewCommentsListArgs) -> str:
    """List a PR's inline review comments (read-only)."""
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    validate_repo(repo)

    comments = await gh_request_paginated("GET", f"repos/{repo}/pulls/{int(pr)}/comments")

    results = []
    for c in comments:
        user = c.get("user", {})
        login = user.get("login", "")
        if bot_only:
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
    return "\n".join(json.dumps(r) for r in results)


async def gh_review_threads_get(args: ReviewThreadsGetArgs) -> str:
    """List a PR's review threads with ids and resolved state (read-only)."""
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    validate_repo(repo)
    owner, _, name = repo.partition("/")

    payload = {"query": _THREADS_QUERY, "variables": {"owner": owner, "name": name, "pr": int(pr)}}
    resp = await gh_request("POST", "graphql", json=payload)
    data = resp.json()

    if (
        bot_only
        and "data" in data
        and data["data"].get("repository")
        and data["data"]["repository"].get("pullRequest")
        and data["data"]["repository"]["pullRequest"].get("reviewThreads")
        and data["data"]["repository"]["pullRequest"]["reviewThreads"].get("nodes")
    ):
        nodes = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        filtered_nodes = []
        for node in nodes:
            keep = False
            for c in node.get("comments", {}).get("nodes", []):
                author = c.get("author", {}) or {}
                if (
                    author.get("__typename") == "Bot"
                    or "copilot" in author.get("login", "").lower()
                ):
                    keep = True
                    break
            if keep:
                filtered_nodes.append(node)
        data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"] = filtered_nodes

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
