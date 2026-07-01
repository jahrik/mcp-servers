from __future__ import annotations

from mcp_servers._common import run_gh, validate_ref, validate_repo

from ..models.schemas import RunArgs, RunListArgs

_RUN_FIELDS = "databaseId,name,displayTitle,status,conclusion,headBranch,headSha,url,updatedAt"


def gh_run_list(args: RunListArgs) -> str:
    """List GitHub Actions workflow runs for a repo.

    Args:
        repo: Repository as ``owner/name``.
        branch: Optional branch name to filter by.
        workflow: Optional workflow name or filename to filter by.
        limit: Maximum number of runs to return (1-100).
    """
    repo = args.repo
    branch = args.branch
    workflow = args.workflow
    limit = args.limit
    validate_repo(repo)
    if branch is not None:
        validate_ref(branch)
    limit = max(1, min(limit, 100))
    cmd_args = ["run", "list", "-R", repo, "--limit", str(limit), "--json", _RUN_FIELDS]
    if branch is not None:
        cmd_args += ["--branch", branch]
    if workflow is not None:
        cmd_args += ["--workflow", workflow]
    return run_gh(cmd_args)


def gh_run_get(args: RunArgs) -> str:
    """Get details of a specific GitHub Actions workflow run.

    Args:
        repo: Repository as ``owner/name``.
        run_id: The run ID (databaseId).
    """
    repo = args.repo
    run_id = args.run_id
    validate_repo(repo)
    return run_gh(
        [
            "run",
            "view",
            str(int(run_id)),
            "-R",
            repo,
            "--json",
            f"{_RUN_FIELDS},jobs",
        ]
    )


def gh_run_failed_logs(args: RunArgs) -> str:
    """Get the failed logs for a GitHub Actions workflow run.

    Args:
        repo: Repository as ``owner/name``.
        run_id: The run ID (databaseId).
    """
    repo = args.repo
    run_id = args.run_id
    validate_repo(repo)
    return run_gh(["run", "view", str(int(run_id)), "-R", repo, "--log-failed"])
