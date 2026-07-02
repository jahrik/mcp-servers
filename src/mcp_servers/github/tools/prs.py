from __future__ import annotations

import json

from mcp_servers.github.client import gh_request, validate_repo

from ..models.schemas import (
    PrArgs,
    PrCommentArgs,
    PrCreateArgs,
    PrEditArgs,
    PrListArgs,
    PrMergeArgs,
)
from ..utils import _audit_log


async def gh_pr_list(args: PrListArgs) -> str:
    """List pull requests for a repo."""
    repo = args.repo
    state = args.state
    limit = args.limit
    validate_repo(repo)
    limit = max(1, min(limit, 100))
    resp = await gh_request(
        "GET", f"repos/{repo}/pulls", params={"state": state, "per_page": limit}
    )
    items = resp.json()
    results = []
    for r in items:
        results.append(
            {
                "number": r.get("number"),
                "title": r.get("title"),
                "state": r.get("state"),
                "author": {"login": r.get("user", {}).get("login")} if r.get("user") else {},
                "headRefName": r.get("head", {}).get("ref"),
                "baseRefName": r.get("base", {}).get("ref"),
                "isDraft": r.get("draft"),
                "url": r.get("html_url"),
                "updatedAt": r.get("updated_at"),
            }
        )
    return json.dumps(results)


async def gh_pr_get(args: PrArgs) -> str:
    """Get a single pull request's metadata."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    resp = await gh_request("GET", f"repos/{repo}/pulls/{number}")
    r = resp.json()

    files_resp = await gh_request("GET", f"repos/{repo}/pulls/{number}/files")
    files_data = files_resp.json()

    result = {
        "number": r.get("number"),
        "title": r.get("title"),
        "state": r.get("state"),
        "author": {"login": r.get("user", {}).get("login")} if r.get("user") else {},
        "headRefName": r.get("head", {}).get("ref"),
        "baseRefName": r.get("base", {}).get("ref"),
        "isDraft": r.get("draft"),
        "url": r.get("html_url"),
        "updatedAt": r.get("updated_at"),
        "body": r.get("body"),
        "additions": r.get("additions"),
        "deletions": r.get("deletions"),
        "files": [
            {
                "path": f.get("filename"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
            }
            for f in files_data
        ],
    }
    return json.dumps(result)


async def gh_pr_diff(args: PrArgs) -> str:
    """Get the unified diff for a pull request."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    resp = await gh_request(
        "GET", f"repos/{repo}/pulls/{number}", headers={"Accept": "application/vnd.github.v3.diff"}
    )
    return resp.text


_PASS_CONCLUSIONS = {"success", "neutral"}
_FAIL_CONCLUSIONS = {"failure", "timed_out", "action_required", "stale"}


def _check_bucket(status: str | None, conclusion: str | None) -> str:
    """Mirror gh CLI's pass/fail/pending/skipping/cancel bucketing of a check run."""
    if status != "completed":
        return "pending"
    if conclusion == "cancelled":
        return "cancel"
    if conclusion == "skipped":
        return "skipping"
    if conclusion in _PASS_CONCLUSIONS:
        return "pass"
    return "fail"


async def gh_pr_checks(args: PrArgs) -> str:
    """Get the status of checks for a pull request."""
    repo = args.repo
    number = args.number
    validate_repo(repo)

    pr_resp = await gh_request("GET", f"repos/{repo}/pulls/{number}")
    sha = pr_resp.json().get("head", {}).get("sha")

    checks_resp = await gh_request("GET", f"repos/{repo}/commits/{sha}/check-runs")
    check_runs = checks_resp.json().get("check_runs", [])

    results = []
    for c in check_runs:
        status = c.get("status")
        conclusion = c.get("conclusion")
        output = c.get("output") or {}
        results.append(
            {
                "name": c.get("name"),
                "state": conclusion or status,
                "bucket": _check_bucket(status, conclusion),
                "description": output.get("title") or output.get("summary"),
                "startedAt": c.get("started_at"),
                "completedAt": c.get("completed_at"),
                "link": c.get("html_url"),
            }
        )
    return json.dumps(results)


@_audit_log
async def gh_pr_create(args: PrCreateArgs) -> str:
    """Create a pull request."""
    repo = args.repo
    validate_repo(repo)
    data = {"title": args.title, "body": args.body, "head": args.head}
    if args.base:
        data["base"] = args.base
    if args.draft:  # pragma: no cover
        data["draft"] = args.draft
    resp = await gh_request("POST", f"repos/{repo}/pulls", json=data)
    return json.dumps(resp.json())


@_audit_log
async def gh_pr_edit(args: PrEditArgs) -> str:
    """Edit a pull request."""
    repo = args.repo
    pr = args.pr
    validate_repo(repo)
    data = {}
    if args.title is not None:
        data["title"] = args.title
    if args.body is not None:  # pragma: no cover
        data["body"] = args.body
    resp = await gh_request("PATCH", f"repos/{repo}/pulls/{pr}", json=data)
    return json.dumps(resp.json())


@_audit_log
async def gh_pr_comment(args: PrCommentArgs) -> str:
    """Add a comment to a pull request."""
    repo = args.repo
    pr = args.pr
    validate_repo(repo)
    resp = await gh_request("POST", f"repos/{repo}/issues/{pr}/comments", json={"body": args.body})
    return json.dumps(resp.json())


@_audit_log
async def gh_pr_merge(args: PrMergeArgs) -> str:
    """Merge a pull request."""
    if not args.confirm:
        raise ValueError("Must set confirm=True")
    repo = args.repo
    pr = args.pr
    validate_repo(repo)

    pr_resp = await gh_request("GET", f"repos/{repo}/pulls/{pr}")
    head_ref = pr_resp.json().get("head", {}).get("ref")

    resp = await gh_request(
        "PUT", f"repos/{repo}/pulls/{pr}/merge", json={"merge_method": args.merge_method}
    )
    result = resp.json()

    if args.delete_branch and head_ref:
        try:
            await gh_request("DELETE", f"repos/{repo}/git/refs/heads/{head_ref}")
        except Exception as e:
            # Merge already succeeded; surface the cleanup failure instead of hiding it.
            result["branch_delete_error"] = str(e)

    return json.dumps(result)
