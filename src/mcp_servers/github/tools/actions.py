from __future__ import annotations

import json

from mcp_servers.github.client import GhError, gh_request, validate_ref, validate_repo

from ..models.schemas import RunArgs, RunListArgs


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


async def gh_run_get(args: RunArgs) -> str:
    """Get details of a specific GitHub Actions workflow run."""
    repo = args.repo
    run_id = args.run_id
    validate_repo(repo)

    run_resp = await gh_request("GET", f"repos/{repo}/actions/runs/{run_id}")
    r = run_resp.json()

    jobs_resp = await gh_request("GET", f"repos/{repo}/actions/runs/{run_id}/jobs")
    jobs = jobs_resp.json().get("jobs", [])

    result = {
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
