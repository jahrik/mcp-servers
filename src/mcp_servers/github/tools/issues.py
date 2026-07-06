from __future__ import annotations

import json
from typing import Any

from mcp_servers.github.client import gh_request, validate_repo

from ..models.schemas import (
    IssueArgs,
    IssueCommentArgs,
    IssueCreateArgs,
    IssueEditArgs,
    IssueListArgs,
)
from ..utils import _audit_log


async def gh_issue_list(args: IssueListArgs) -> str:
    """List issues for a repo.

    Args:
        repo: Repository as ``owner/name``.
        state: ``open``, ``closed``, or ``all``.
        limit: Maximum number of issues to return (1-100).
    """
    repo = args.repo
    state = args.state
    limit = args.limit
    validate_repo(repo)
    limit = max(1, min(limit, 100))
    resp = await gh_request(
        "GET", f"repos/{repo}/issues", params={"state": state, "per_page": limit}
    )
    items = resp.json()
    results = []
    for r in items:
        # Pull requests are also issues in GitHub API; usually gh issue list filters them out
        if "pull_request" in r:
            continue
        results.append(
            {
                "number": r.get("number"),
                "title": r.get("title"),
                "state": r.get("state"),
                "author": {"login": r.get("user", {}).get("login")} if r.get("user") else {},
                "labels": [{"name": lbl.get("name")} for lbl in r.get("labels", [])],
                "url": r.get("html_url"),
                "updatedAt": r.get("updated_at"),
            }
        )
    return json.dumps(results[:limit])


async def gh_issue_get(args: IssueArgs) -> str:
    """Get a single issue's metadata and body."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    resp = await gh_request("GET", f"repos/{repo}/issues/{number}")
    r = resp.json()

    comments_resp = await gh_request("GET", f"repos/{repo}/issues/{number}/comments")
    comments = comments_resp.json()

    result = {
        "number": r.get("number"),
        "title": r.get("title"),
        "state": r.get("state"),
        "author": {"login": r.get("user", {}).get("login")} if r.get("user") else {},
        "labels": [{"name": lbl.get("name")} for lbl in r.get("labels", [])],
        "url": r.get("html_url"),
        "updatedAt": r.get("updated_at"),
        "body": r.get("body"),
        "comments": [
            {
                "author": {"login": c.get("user", {}).get("login")} if c.get("user") else {},
                "body": c.get("body"),
                "updatedAt": c.get("updated_at"),
            }
            for c in comments
        ],
    }
    return json.dumps(result)


@_audit_log
async def gh_issue_create(args: IssueCreateArgs) -> str:
    """Create an issue.

    Args:
        repo: Repository as ``owner/name``.
        title: Title of the issue.
        body: Body/description of the issue.
    """
    repo = args.repo
    title = args.title
    body = args.body
    validate_repo(repo)
    resp = await gh_request("POST", f"repos/{repo}/issues", json={"title": title, "body": body})
    return json.dumps(resp.json())


@_audit_log
async def gh_issue_comment(args: IssueCommentArgs) -> str:
    """Add a comment to an issue.

    Args:
        repo: Repository as ``owner/name``.
        issue: Issue number.
        body: The comment body.
    """
    repo = args.repo
    issue = args.issue
    body = args.body
    validate_repo(repo)
    resp = await gh_request("POST", f"repos/{repo}/issues/{issue}/comments", json={"body": body})
    return json.dumps(resp.json())


@_audit_log
async def gh_issue_edit(args: IssueEditArgs) -> str:
    """Edit an issue's state or metadata (close/reopen, title, body, labels).

    Only the fields you set are sent. ``state='closed'`` with
    ``state_reason='completed'`` or ``'not_planned'`` closes the issue;
    ``state='open'`` reopens it. Convention: close only your own stale or
    resolved issues, never triage the maintainer's.
    """
    repo = args.repo
    number = args.number
    validate_repo(repo)
    data: dict[str, Any] = {}
    if args.state is not None:
        data["state"] = args.state
    if args.state_reason is not None:
        data["state_reason"] = args.state_reason
    if args.title is not None:
        data["title"] = args.title
    if args.body is not None:
        data["body"] = args.body
    if args.labels is not None:
        data["labels"] = args.labels
    resp = await gh_request("PATCH", f"repos/{repo}/issues/{number}", json=data)
    return json.dumps(resp.json())
