from __future__ import annotations

import json
from typing import Any

from mcp_servers.github.client import gh_request, validate_repo

from ..models.schemas import MilestoneCreateArgs, MilestoneListArgs
from ..utils import _audit_log


@_audit_log
async def gh_milestone_create(args: MilestoneCreateArgs) -> str:
    """Create a milestone."""
    repo = args.repo
    validate_repo(repo)
    data: dict[str, Any] = {"title": args.title}
    if args.description is not None:
        data["description"] = args.description
    if args.due_on is not None:
        data["due_on"] = args.due_on
    resp = await gh_request("POST", f"repos/{repo}/milestones", json=data)
    r = resp.json()
    return json.dumps(
        {
            "number": r.get("number"),
            "title": r.get("title"),
            "description": r.get("description"),
            "state": r.get("state"),
            "dueOn": r.get("due_on"),
            "url": r.get("html_url"),
        }
    )


async def gh_milestone_list(args: MilestoneListArgs) -> str:
    """List milestones for a repo."""
    repo = args.repo
    validate_repo(repo)
    resp = await gh_request("GET", f"repos/{repo}/milestones", params={"state": args.state})
    items = resp.json()
    results = [
        {
            "number": r.get("number"),
            "title": r.get("title"),
            "description": r.get("description"),
            "state": r.get("state"),
            "dueOn": r.get("due_on"),
            "openIssues": r.get("open_issues"),
            "closedIssues": r.get("closed_issues"),
            "url": r.get("html_url"),
        }
        for r in items
    ]
    return json.dumps(results)
