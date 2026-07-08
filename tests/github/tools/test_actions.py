from __future__ import annotations

import json

import pytest

from mcp_servers.github.models.schemas import RunArgs, RunListArgs, RunRerunArgs
from mcp_servers.github.tools.actions import (
    gh_run_failed_logs,
    gh_run_get,
    gh_run_list,
    gh_run_rerun,
)


@pytest.mark.asyncio
async def test_gh_run_list(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs?per_page=10",
        json={"workflow_runs": [{"id": 1, "name": "CI"}]},
    )
    res = await gh_run_list(RunListArgs(repo="octocat/repo", limit=10))
    assert json.loads(res)[0]["databaseId"] == 1


@pytest.mark.asyncio
async def test_gh_run_list_with_workflow(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/workflows/ci.yml/runs?per_page=10",
        json={"workflow_runs": [{"id": 2}]},
    )
    res = await gh_run_list(RunListArgs(repo="octocat/repo", limit=10, workflow="ci.yml"))
    assert json.loads(res)[0]["databaseId"] == 2


@pytest.mark.asyncio
async def test_gh_run_get(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs/1", json={"id": 1}
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/jobs",
        json={"jobs": [{"name": "test", "status": "completed", "conclusion": "success"}]},
    )
    res = await gh_run_get(RunArgs(repo="octocat/repo", run_id=1))
    data = json.loads(res)
    assert data["databaseId"] == 1
    assert data["jobs"][0]["name"] == "test"


@pytest.mark.asyncio
async def test_gh_run_failed_logs(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/jobs",
        json={
            "jobs": [
                {"id": 10, "name": "test", "conclusion": "failure"},
                {"id": 11, "name": "build", "conclusion": "success"},
            ]
        },
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/jobs/10/logs", text="log error"
    )
    res = await gh_run_failed_logs(RunArgs(repo="octocat/repo", run_id=1))
    assert "log error" in res


@pytest.mark.asyncio
async def test_gh_run_failed_logs_unavailable(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/jobs",
        json={"jobs": [{"id": 10, "name": "test", "conclusion": "failure"}]},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/jobs/10/logs", status_code=404
    )
    res = await gh_run_failed_logs(RunArgs(repo="octocat/repo", run_id=1))
    assert "Logs not available" in res


@pytest.mark.asyncio
async def test_gh_run_failed_logs_none(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/jobs",
        json={"jobs": [{"id": 10, "name": "test", "conclusion": "success"}]},
    )
    res = await gh_run_failed_logs(RunArgs(repo="octocat/repo", run_id=1))
    assert "No failed jobs found" in res


@pytest.mark.asyncio
async def test_gh_run_failed_logs_non404_error_propagates(httpx_mock):
    """Non-404 errors (auth failures, 5xx) must propagate instead of being swallowed."""
    from mcp_servers.github.client import GhError

    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/jobs",
        json={"jobs": [{"id": 10, "name": "test", "conclusion": "failure"}]},
    )
    httpx_mock.add_response(
        url="https://api.github.com/repos/octocat/repo/actions/jobs/10/logs",
        status_code=500,
        text="Internal Server Error",
    )
    with pytest.raises(GhError) as exc_info:
        await gh_run_failed_logs(RunArgs(repo="octocat/repo", run_id=1))
    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_gh_run_rerun(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="POST",
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/rerun",
        status_code=201,
    )
    res = await gh_run_rerun(RunRerunArgs(repo="octocat/repo", run_id=1))
    assert "triggered" in res


@pytest.mark.asyncio
async def test_gh_run_rerun_failed_only(httpx_mock, monkeypatch):
    monkeypatch.setenv("MCP_GITHUB_ALLOW_WRITE", "1")
    httpx_mock.add_response(
        method="POST",
        url="https://api.github.com/repos/octocat/repo/actions/runs/1/rerun-failed-jobs",
        status_code=201,
    )
    res = await gh_run_rerun(RunRerunArgs(repo="octocat/repo", run_id=1, failed_only=True))
    assert "triggered" in res
