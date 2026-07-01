from __future__ import annotations

from mcp_servers._common import run_gh, validate_repo

from ..models.schemas import (
    IssueArgs,
    IssueCommentArgs,
    IssueCreateArgs,
    IssueListArgs,
)
from ..utils import _audit_log

_ISSUE_FIELDS = "number,title,state,author,labels,url,updatedAt"


def gh_issue_list(args: IssueListArgs) -> str:
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
    return run_gh(
        [
            "issue",
            "list",
            "-R",
            repo,
            "--state",
            state,
            "--limit",
            str(limit),
            "--json",
            _ISSUE_FIELDS,
        ]
    )


def gh_issue_get(args: IssueArgs) -> str:
    """Get a single issue's metadata and body."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    return run_gh(
        ["issue", "view", str(int(number)), "-R", repo, "--json", f"{_ISSUE_FIELDS},body,comments"]
    )


@_audit_log
def gh_issue_create(args: IssueCreateArgs) -> str:
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
    return run_gh(["issue", "create", "-R", repo, "--title", title, "--body", body])


@_audit_log
def gh_issue_comment(args: IssueCommentArgs) -> str:
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
    return run_gh(["issue", "comment", str(int(issue)), "-R", repo, "--body", body])
