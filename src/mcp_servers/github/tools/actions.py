from __future__ import annotations

import asyncio
import json
import time

from mcp_servers.github.client import GhError, gh_request, validate_ref, validate_repo

from ..models.schemas import RunArgs, RunListArgs, RunRerunArgs
from ..utils import _audit_log


async def gh_run_list(args: RunListArgs) -> str:
    """List GitHub Actions workflow runs for a repo."""
    repo = args.repo
    branch = args.branch
    workflow = args.workflow
    limit = args.limit
    validate_repo(repo)
    if branch is not None:  # pragma: no cover
        validate_ref(branch)
    limit = max(1, min(limit, 100))

    params = {"per_page": limit}
    if branch:  # pragma: no cover
        params["branch"] = branch

    endpoint = f"repos/{repo}/actions/runs"
    if workflow:
        endpoint = f"repos/{repo}/actions/workflows/{workflow}/runs"

    resp = await gh_request("GET", endpoint, params=params)
    runs = resp.json().get("workflow_runs", [])

    results = []
    for r in runs:
        results.append(
            {
                "databaseId": r.get("id"),
                "name": r.get("name"),
                "displayTitle": r.get("display_title"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "headBranch": r.get("head_branch"),
                "headSha": r.get("head_sha"),
                "url": r.get("html_url"),
                "updatedAt": r.get("updated_at"),
            }
        )
    return json.dumps(results[:limit])


async def _fetch_run(repo: str, run_id: int) -> dict:
    run_resp = await gh_request("GET", f"repos/{repo}/actions/runs/{run_id}")
    r = run_resp.json()

    jobs_resp = await gh_request("GET", f"repos/{repo}/actions/runs/{run_id}/jobs")
    jobs = jobs_resp.json().get("jobs", [])

    return {
        "databaseId": r.get("id"),
        "name": r.get("name"),
        "displayTitle": r.get("display_title"),
        "status": r.get("status"),
        "conclusion": r.get("conclusion"),
        "headBranch": r.get("head_branch"),
        "headSha": r.get("head_sha"),
        "url": r.get("html_url"),
        "updatedAt": r.get("updated_at"),
        "jobs": [
            {"name": j.get("name"), "status": j.get("status"), "conclusion": j.get("conclusion")}
            for j in jobs
        ],
    }


async def gh_run_get(args: RunArgs) -> str:
    """Get details of a specific GitHub Actions workflow run.

    With ``wait_for_completion=True``, polls in-process until ``status ==
    "completed"`` or ``timeout_seconds`` elapses, then returns the final (or
    last-seen) run details in the same shape as a plain snapshot call — so an
    agent watching a run doesn't have to loop calls across separate turns.
    """
    repo = args.repo
    run_id = args.run_id
    validate_repo(repo)

    result = await _fetch_run(repo, run_id)
    if not args.wait_for_completion:
        return json.dumps(result)

    deadline = time.monotonic() + args.timeout_seconds
    while result.get("status") != "completed" and time.monotonic() < deadline:
        await asyncio.sleep(args.poll_interval_seconds)
        result = await _fetch_run(repo, run_id)

    return json.dumps(result)


async def gh_run_failed_logs(args: RunArgs) -> str:
    """Get the failed logs for a GitHub Actions workflow run."""
    repo = args.repo
    run_id = args.run_id
    validate_repo(repo)

    jobs_resp = await gh_request("GET", f"repos/{repo}/actions/runs/{run_id}/jobs")
    jobs = jobs_resp.json().get("jobs", [])

    failed_jobs = [j for j in jobs if j.get("conclusion") == "failure"]

    logs = []
    for j in failed_jobs:
        job_id = j.get("id")
        try:
            log_resp = await gh_request("GET", f"repos/{repo}/actions/jobs/{job_id}/logs")
            logs.append(f"--- Job: {j.get('name')} ---\n{log_resp.text}")
        except GhError as e:
            if e.status_code != 404:
                raise
            logs.append(f"--- Job: {j.get('name')} ---\n(Logs not available)")

    if not logs:
        return "No failed jobs found or logs unavailable."
    return "\n\n".join(logs)


@_audit_log
async def gh_run_rerun(args: RunRerunArgs) -> str:
    """Rerun a GitHub Actions workflow run (or only its failed jobs)."""
    repo = args.repo
    run_id = args.run_id
    failed_only = args.failed_only
    validate_repo(repo)

    if failed_only:
        endpoint = f"repos/{repo}/actions/runs/{run_id}/rerun-failed-jobs"
    else:
        endpoint = f"repos/{repo}/actions/runs/{run_id}/rerun"

    await gh_request("POST", endpoint)
    return "Rerun triggered successfully."
