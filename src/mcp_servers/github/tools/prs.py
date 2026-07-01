from __future__ import annotations

from mcp_servers._common import run_gh, validate_repo

from ..models.schemas import (
    PrArgs,
    PrCommentArgs,
    PrCreateArgs,
    PrEditArgs,
    PrListArgs,
    PrMergeArgs,
)
from ..utils import _audit_log

_PR_FIELDS = "number,title,state,author,headRefName,baseRefName,isDraft,url,updatedAt"
_CHECK_FIELDS = "name,state,bucket,startedAt,completedAt,link,description,workflow"


def gh_pr_list(args: PrListArgs) -> str:
    """List pull requests for a repo.

    Args:
        repo: Repository as ``owner/name``.
        state: ``open``, ``closed``, ``merged``, or ``all``.
        limit: Maximum number of PRs to return (1-100).
    """
    repo = args.repo
    state = args.state
    limit = args.limit
    validate_repo(repo)
    limit = max(1, min(limit, 100))
    return run_gh(
        ["pr", "list", "-R", repo, "--state", state, "--limit", str(limit), "--json", _PR_FIELDS]
    )


def gh_pr_get(args: PrArgs) -> str:
    """Get a single pull request's metadata (title, body, state, refs)."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    return run_gh(
        [
            "pr",
            "view",
            str(int(number)),
            "-R",
            repo,
            "--json",
            f"{_PR_FIELDS},body,additions,deletions,files",
        ]
    )


def gh_pr_diff(args: PrArgs) -> str:
    """Get the unified diff for a pull request."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    return run_gh(["pr", "diff", str(int(number)), "-R", repo])


def gh_pr_checks(args: PrArgs) -> str:
    """Get the status of checks for a pull request.

    Args:
        repo: Repository as ``owner/name``.
        number: Pull request number.
    """
    repo = args.repo
    number = args.number
    validate_repo(repo)
    return run_gh(
        [
            "pr",
            "checks",
            str(int(number)),
            "-R",
            repo,
            "--json",
            _CHECK_FIELDS,
        ]
    )


@_audit_log
def gh_pr_create(args: PrCreateArgs) -> str:
    """Create a pull request.

    Args:
        repo: Repository as ``owner/name``.
        title: Title of the pull request.
        body: Body/description of the pull request.
        head: The branch that contains the commits for your pull request.
        base: The branch into which you want your code merged.
        draft: Mark the pull request as a draft.
    """
    repo = args.repo
    title = args.title
    body = args.body
    head = args.head
    base = args.base
    draft = args.draft
    validate_repo(repo)
    cmd_args = ["pr", "create", "-R", repo, "--title", title, "--body", body, "--head", head]
    if base is not None:
        cmd_args += ["--base", base]
    if draft:
        cmd_args += ["--draft"]
    return run_gh(cmd_args)


@_audit_log
def gh_pr_edit(args: PrEditArgs) -> str:
    """Edit a pull request.

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        title: Optional new title.
        body: Optional new body.
    """
    repo = args.repo
    pr = args.pr
    title = args.title
    body = args.body
    validate_repo(repo)
    cmd_args = ["pr", "edit", str(int(pr)), "-R", repo]
    if title is not None:
        cmd_args += ["--title", title]
    if body is not None:
        cmd_args += ["--body", body]
    return run_gh(cmd_args)


@_audit_log
def gh_pr_comment(args: PrCommentArgs) -> str:
    """Add a comment to a pull request.

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        body: The comment body.
    """
    repo = args.repo
    pr = args.pr
    body = args.body
    validate_repo(repo)
    return run_gh(["pr", "comment", str(int(pr)), "-R", repo, "--body", body])


@_audit_log
def gh_pr_merge(args: PrMergeArgs) -> str:
    """Merge a pull request.

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        merge_method: ``squash``, ``merge``, or ``rebase``. Default is ``squash``.
        delete_branch: Delete the local and remote branch after merge.
    """
    if not args.confirm:
        raise ValueError("Must set confirm=True")
    repo = args.repo
    pr = args.pr
    merge_method = args.merge_method
    delete_branch = args.delete_branch
    validate_repo(repo)
    cmd_args = ["pr", "merge", str(int(pr)), "-R", repo, f"--{merge_method}"]
    if delete_branch:
        cmd_args += ["--delete-branch"]
    return run_gh(cmd_args)
