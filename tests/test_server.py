"""Tests for the GitHub MCP server."""

from __future__ import annotations

from pytest_mock import MockerFixture

from mcp_servers.github.server import (
    get_file,
    get_issue,
    get_pr,
    get_review_threads,
    get_run,
    list_issues,
    list_prs,
    list_review_comments,
    list_runs,
    main,
    pr_checks,
    pr_diff,
    reply_review_comment,
    resolve_review_thread,
    run_failed_logs,
    search_code,
    search_issues,
    search_prs,
)


def test_list_prs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock pr list")
    result = list_prs("owner/repo", state="open", limit=5)
    assert result == "mock pr list"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "list" in args
    assert "owner/repo" in args
    assert "5" in args


def test_get_pr(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock pr output")
    result = get_pr("owner/repo", 123)
    assert result == "mock pr output"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "view" in args
    assert "123" in args


def test_pr_diff(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock pr diff")
    result = pr_diff("owner/repo", 123)
    assert result == "mock pr diff"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "diff" in args
    assert "123" in args


def test_pr_checks(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock pr checks")
    result = pr_checks("owner/repo", 123)
    assert result == "mock pr checks"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "checks" in args
    assert "123" in args


def test_list_issues(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock issues")
    result = list_issues("owner/repo", state="closed", limit=10)
    assert result == "mock issues"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "issue" in args
    assert "list" in args
    assert "owner/repo" in args
    assert "10" in args


def test_get_issue(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock issue output")
    result = get_issue("owner/repo", 456)
    assert result == "mock issue output"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "issue" in args
    assert "view" in args
    assert "456" in args


def test_get_file(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock file content")
    result = get_file("owner/repo", "path/to/file.py", ref="main")
    assert result == "mock file content"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "repos/owner/repo/contents/path/to/file.py" in args
    assert "ref=main" in args


def test_search_code(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock results")
    result = search_code("def foo", repo="owner/repo", limit=50)
    assert result == "mock results"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "search" in args
    assert "code" in args
    assert "def foo" in args
    assert "owner/repo" in args
    assert "50" in args


def test_search_prs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock pr results")
    result = search_prs("is:open", repo="owner/repo", limit=50)
    assert result == "mock pr results"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "search" in args
    assert "prs" in args
    assert "is:open" in args
    assert "owner/repo" in args
    assert "50" in args
    assert "--json" in args


def test_search_issues(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock issues")
    result = search_issues("is:open", repo="owner/repo", limit=50)
    assert result == "mock issues"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "search" in args
    assert "issues" in args
    assert "is:open" in args
    assert "owner/repo" in args
    assert "50" in args
    assert "--json" in args



def test_list_review_comments(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock comments")
    result = list_review_comments("owner/repo", 42)
    assert result == "mock comments"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "repos/owner/repo/pulls/42/comments" in args
    assert "--paginate" in args
    # Default: no bot filter in the jq program.
    jq = args[args.index("--jq") + 1]
    assert "copilot" not in jq


def test_list_review_comments_bot_only(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock bot comments")
    result = list_review_comments("owner/repo", 42, bot_only=True)
    assert result == "mock bot comments"
    args = mock_run_gh.call_args[0][0]
    jq = args[args.index("--jq") + 1]
    assert "select" in jq
    assert "copilot" in jq
    assert "Bot" in jq


def test_get_review_threads(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock threads")
    result = get_review_threads("owner/repo", 42)
    assert result == "mock threads"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "graphql" in args
    assert "owner=owner" in args
    assert "name=repo" in args
    assert "pr=42" in args
    assert any(a.startswith("query=") and "reviewThreads" in a for a in args)
    # Default: no client-side thread filtering.
    assert "--jq" not in args


def test_get_review_threads_bot_only(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock bot threads")
    result = get_review_threads("owner/repo", 42, bot_only=True)
    assert result == "mock bot threads"
    args = mock_run_gh.call_args[0][0]
    assert "--jq" in args
    jq = args[args.index("--jq") + 1]
    assert "reviewThreads.nodes" in jq
    assert "copilot" in jq


def test_reply_review_comment(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock reply")
    result = reply_review_comment("owner/repo", 42, 999, "thanks, fixed")
    assert result == "mock reply"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "POST" in args
    assert "repos/owner/repo/pulls/42/comments/999/replies" in args
    assert "body=thanks, fixed" in args


def test_resolve_review_thread(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock resolved")
    result = resolve_review_thread("PRRT_abc123")
    assert result == "mock resolved"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "graphql" in args
    assert "threadId=PRRT_abc123" in args
    assert any(a.startswith("query=") and "resolveReviewThread" in a for a in args)


def test_list_runs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock list runs")
    result = list_runs("owner/repo", limit=10)
    assert result == "mock list runs"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "run" in args
    assert "list" in args
    assert "owner/repo" in args
    assert "10" in args
    assert "--branch" not in args
    assert "--workflow" not in args


def test_list_runs_with_filters(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock runs")
    result = list_runs("owner/repo", limit=5, branch="main", workflow="ci.yml")
    assert result == "mock runs"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "run" in args
    assert "list" in args
    assert "owner/repo" in args
    assert "5" in args
    assert "--branch" in args
    assert "main" in args
    assert "--workflow" in args
    assert "ci.yml" in args


def test_get_run(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock get run")
    result = get_run("owner/repo", 789)
    assert result == "mock get run"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "run" in args
    assert "view" in args
    assert "789" in args


def test_run_failed_logs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.server.run_gh", return_value="mock logs")
    result = run_failed_logs("owner/repo", 789)
    assert result == "mock logs"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "run" in args
    assert "view" in args
    assert "789" in args
    assert "--log-failed" in args


def test_main(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("mcp_servers.github.server.mcp.run")
    main()
    mock_run.assert_called_once()


def test_main_block(mocker: MockerFixture) -> None:
    import runpy
    mock_run = mocker.patch("mcp.server.fastmcp.FastMCP.run")
    runpy.run_module("mcp_servers.github.server", run_name="__main__")
    mock_run.assert_called_once()

