"""Tests for the GitHub MCP server."""

from __future__ import annotations

from pytest_mock import MockerFixture

from mcp_servers.github.server import (
    get_file,
    get_issue,
    get_pr,
    list_issues,
    list_prs,
    pr_diff,
    search_code,
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
