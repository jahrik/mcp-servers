"""Tests for the GitHub MCP server."""

from __future__ import annotations

import json
import pathlib

import pytest
from pytest_mock import MockerFixture

from mcp_servers.github.models.schemas import (
    ApiGetArgs,
    FileGetArgs,
    GraphqlQueryArgs,
    IssueArgs,
    IssueCommentArgs,
    IssueCreateArgs,
    IssueListArgs,
    PrArgs,
    PrCommentArgs,
    PrCreateArgs,
    PrListArgs,
    PrMergeArgs,
    RepoGetArgs,
    RepoListArgs,
    ReviewCommentReplyArgs,
    ReviewCommentsListArgs,
    ReviewThreadResolveArgs,
    ReviewThreadsGetArgs,
    RunArgs,
    RunListArgs,
    SearchCodeArgs,
    SearchIssuesArgs,
    SearchPrsArgs,
)
from mcp_servers.github.server import main
from mcp_servers.github.tools import (
    gh_api_get,
    gh_file_get,
    gh_graphql_query,
    gh_issue_comment,
    gh_issue_create,
    gh_issue_get,
    gh_issue_list,
    gh_pr_checks,
    gh_pr_comment,
    gh_pr_create,
    gh_pr_diff,
    gh_pr_get,
    gh_pr_list,
    gh_pr_merge,
    gh_repo_get,
    gh_repo_list,
    gh_review_comment_reply,
    gh_review_comments_list,
    gh_review_thread_resolve,
    gh_review_threads_get,
    gh_run_failed_logs,
    gh_run_get,
    gh_run_list,
    gh_search_code,
    gh_search_issues,
    gh_search_prs,
)


@pytest.fixture(autouse=True)
def mock_mcp_dir(mocker: MockerFixture, tmp_path: pathlib.Path) -> None:
    """Ensure no test writes to the real ~/.mcp directory."""
    mocker.patch("os.path.expanduser", return_value=str(tmp_path / ".mcp"))


def test_list_repos(mocker: MockerFixture) -> None:
    import mcp_servers.github.utils

    mcp_servers.github.utils._CACHE.clear()
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.repos.run_gh", return_value="mock repo list"
    )
    result = gh_repo_list(RepoListArgs(limit=5, owner="owner"))
    assert result == "mock repo list"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "repo" in args
    assert "list" in args
    assert "owner" in args
    assert "5" in args

    # hit the cache
    result_cache = gh_repo_list(RepoListArgs(limit=5, owner="owner"))
    assert result_cache == "mock repo list"
    mock_run_gh.assert_called_once()

    result2 = gh_repo_list(RepoListArgs(limit=5, owner="owner", no_cache=True))
    assert result2 == "mock repo list"
    assert mock_run_gh.call_count == 2


def test_get_repo(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.repos.run_gh", return_value="mock repo view"
    )
    result = gh_repo_get(RepoGetArgs(repo="owner/repo"))
    assert result == "mock repo view"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "repo" in args
    assert "view" in args
    assert "owner/repo" in args
    result2 = gh_repo_get(RepoGetArgs(repo="owner/repo", no_cache=True))
    assert result2 == "mock repo view"
    assert mock_run_gh.call_count == 2


def test_list_prs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.prs.run_gh", return_value="mock pr list")
    result = gh_pr_list(PrListArgs(state="open", limit=5, repo="owner/repo"))
    assert result == "mock pr list"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "list" in args
    assert "owner/repo" in args
    assert "5" in args


def test_get_pr(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.prs.run_gh", return_value="mock pr output")
    result = gh_pr_get(PrArgs(repo="owner/repo", number=123))
    assert result == "mock pr output"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "view" in args
    assert "123" in args


def test_pr_diff(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.prs.run_gh", return_value="mock pr diff")
    result = gh_pr_diff(PrArgs(repo="owner/repo", number=123))
    assert result == "mock pr diff"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "diff" in args
    assert "123" in args


def test_pr_checks(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.prs.run_gh", return_value="mock pr checks")
    result = gh_pr_checks(PrArgs(repo="owner/repo", number=123))
    assert result == "mock pr checks"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "checks" in args
    assert "123" in args


def test_create_pr(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.prs.run_gh", return_value="mock pr create")
    result = gh_pr_create(
        PrCreateArgs(
            title="My PR",
            body="Fixes bug",
            head="feature-branch",
            base="main",
            draft=True,
            repo="owner/repo",
        )
    )
    assert result == "mock pr create"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "create" in args
    assert "owner/repo" in args
    assert "--title" in args
    assert "My PR" in args
    assert "--body" in args
    assert "Fixes bug" in args
    assert "--head" in args
    assert "feature-branch" in args
    assert "--base" in args
    assert "main" in args
    assert "--draft" in args


def test_pr_comment(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.prs.run_gh", return_value="mock pr comment"
    )
    result = gh_pr_comment(PrCommentArgs(repo="owner/repo", pr=123, body="LGTM!"))
    assert result == "mock pr comment"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "comment" in args
    assert "123" in args
    assert "owner/repo" in args
    assert "--body" in args
    assert "LGTM!" in args


def test_merge_pr(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.prs.run_gh", return_value="mock pr merge")
    result = gh_pr_merge(
        PrMergeArgs(
            merge_method="rebase", delete_branch=True, repo="owner/repo", pr=123, confirm=True
        )
    )
    assert result == "mock pr merge"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "pr" in args
    assert "merge" in args
    assert "123" in args
    assert "owner/repo" in args
    assert "--rebase" in args
    assert "--delete-branch" in args


def test_merge_pr_invalid_method(mocker: MockerFixture) -> None:
    import pytest

    with pytest.raises(ValueError, match="Invalid merge method"):
        gh_pr_merge(PrMergeArgs(merge_method="invalid", repo="owner/repo", pr=123, confirm=True))


def test_merge_pr_unconfirmed(mocker: MockerFixture) -> None:
    import pytest

    with pytest.raises(ValueError, match="Must set confirm=True"):
        gh_pr_merge(PrMergeArgs(merge_method="squash", repo="owner/repo", pr=123, confirm=False))


def test_list_issues(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.issues.run_gh", return_value="mock issues")
    result = gh_issue_list(IssueListArgs(state="closed", limit=10, repo="owner/repo"))
    assert result == "mock issues"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "issue" in args
    assert "list" in args
    assert "owner/repo" in args
    assert "10" in args


def test_get_issue(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.issues.run_gh", return_value="mock issue output"
    )
    result = gh_issue_get(IssueArgs(repo="owner/repo", number=456))
    assert result == "mock issue output"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "issue" in args
    assert "view" in args
    assert "456" in args


def test_create_issue(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.issues.run_gh", return_value="mock issue create"
    )
    result = gh_issue_create(
        IssueCreateArgs(title="My Issue", body="Issue body", repo="owner/repo")
    )
    assert result == "mock issue create"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "issue" in args
    assert "create" in args
    assert "owner/repo" in args
    assert "--title" in args
    assert "My Issue" in args
    assert "--body" in args
    assert "Issue body" in args


def test_issue_comment(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.issues.run_gh", return_value="mock issue comment"
    )
    result = gh_issue_comment(IssueCommentArgs(repo="owner/repo", issue=456, body="Fixing this"))
    assert result == "mock issue comment"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "issue" in args
    assert "comment" in args
    assert "456" in args
    assert "owner/repo" in args
    assert "--body" in args
    assert "Fixing this" in args


def test_get_file(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.api.run_gh", return_value="mock file content"
    )
    result = gh_file_get(FileGetArgs(ref="main", repo="owner/repo", path="path/to/file.py"))
    assert result == "mock file content"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "repos/owner/repo/contents/path/to/file.py" in args
    assert "ref=main" in args


def test_search_code(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.api.run_gh", return_value="mock results")
    result = gh_search_code(SearchCodeArgs(repo="owner/repo", limit=50, query="def foo"))
    assert result == "mock results"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "search" in args
    assert "code" in args
    assert "def foo" in args
    assert "owner/repo" in args
    assert "50" in args


def test_search_prs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.api.run_gh", return_value="mock pr results"
    )
    result = gh_search_prs(SearchPrsArgs(repo="owner/repo", limit=50, query="is:open"))
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
    mock_run_gh = mocker.patch("mcp_servers.github.tools.api.run_gh", return_value="mock issues")
    result = gh_search_issues(SearchIssuesArgs(repo="owner/repo", limit=50, query="is:open"))
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
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.reviews.run_gh", return_value="mock comments"
    )
    result = gh_review_comments_list(ReviewCommentsListArgs(repo="owner/repo", pr=42))
    assert result == "mock comments"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "repos/owner/repo/pulls/42/comments" in args
    assert "--paginate" in args
    jq = args[args.index("--jq") + 1]
    assert "copilot" not in jq


def test_list_review_comments_bot_only(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.reviews.run_gh", return_value="mock bot comments"
    )
    result = gh_review_comments_list(
        ReviewCommentsListArgs(bot_only=True, repo="owner/repo", pr=42)
    )
    assert result == "mock bot comments"
    args = mock_run_gh.call_args[0][0]
    jq = args[args.index("--jq") + 1]
    assert "select" in jq
    assert "copilot" in jq
    assert "Bot" in jq


def test_get_review_threads(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.reviews.run_gh", return_value="mock threads"
    )
    result = gh_review_threads_get(ReviewThreadsGetArgs(repo="owner/repo", pr=42))
    assert result == "mock threads"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "graphql" in args
    assert "owner=owner" in args
    assert "name=repo" in args
    assert "pr=42" in args
    assert any(a.startswith("query=") and "reviewThreads" in a for a in args)
    assert "--jq" not in args


def test_get_review_threads_bot_only(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.reviews.run_gh", return_value="mock bot threads"
    )
    result = gh_review_threads_get(ReviewThreadsGetArgs(bot_only=True, repo="owner/repo", pr=42))
    assert result == "mock bot threads"
    args = mock_run_gh.call_args[0][0]
    assert "--jq" in args
    jq = args[args.index("--jq") + 1]
    assert "reviewThreads.nodes" in jq
    assert "copilot" in jq


def test_reply_review_comment(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.reviews.run_gh", return_value="mock reply")
    result = gh_review_comment_reply(
        ReviewCommentReplyArgs(repo="owner/repo", pr=42, comment_id=999, body="thanks, fixed")
    )
    assert result == "mock reply"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "POST" in args
    assert "repos/owner/repo/pulls/42/comments/999/replies" in args
    assert "body=thanks, fixed" in args


def test_resolve_review_thread(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.reviews.run_gh", return_value="mock resolved"
    )
    result = gh_review_thread_resolve(ReviewThreadResolveArgs(thread_id="PRRT_abc123"))
    assert result == "mock resolved"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "graphql" in args
    assert "threadId=PRRT_abc123" in args
    assert any(a.startswith("query=") and "resolveReviewThread" in a for a in args)


def test_list_runs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.actions.run_gh", return_value="mock list runs"
    )
    result = gh_run_list(RunListArgs(limit=10, repo="owner/repo"))
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
    mock_run_gh = mocker.patch("mcp_servers.github.tools.actions.run_gh", return_value="mock runs")
    result = gh_run_list(RunListArgs(limit=5, branch="main", workflow="ci.yml", repo="owner/repo"))
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
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.actions.run_gh", return_value="mock get run"
    )
    result = gh_run_get(RunArgs(repo="owner/repo", run_id=789))
    assert result == "mock get run"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "run" in args
    assert "view" in args
    assert "789" in args


def test_run_failed_logs(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.actions.run_gh", return_value="mock logs")
    result = gh_run_failed_logs(RunArgs(repo="owner/repo", run_id=789))
    assert result == "mock logs"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "run" in args
    assert "view" in args
    assert "789" in args
    assert "--log-failed" in args


def test_api_get(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch("mcp_servers.github.tools.api.run_gh", return_value="mock api get")
    result = gh_api_get(ApiGetArgs(jq_filter=".[] | .url", endpoint="repos/owner/repo/pulls"))
    assert result == "mock api get"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "repos/owner/repo/pulls" in args
    assert "--jq" in args
    assert ".[] | .url" in args


def test_graphql_query(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.api.run_gh", return_value="mock graphql query"
    )
    result = gh_graphql_query(
        GraphqlQueryArgs(jq_filter=".data.viewer.login", query="query { viewer { login } }")
    )
    assert result == "mock graphql query"
    mock_run_gh.assert_called_once()
    args = mock_run_gh.call_args[0][0]
    assert "api" in args
    assert "graphql" in args
    assert "-f" in args
    assert "query=query { viewer { login } }" in args
    assert "--jq" in args
    assert ".data.viewer.login" in args


def test_graphql_query_mutation(mocker: MockerFixture) -> None:
    import pytest

    with pytest.raises(ValueError, match="Mutations are not allowed"):
        gh_graphql_query(GraphqlQueryArgs(query="mutation { update() }"))


def test_main(mocker: MockerFixture) -> None:
    mock_run = mocker.patch("mcp_servers.github.server.mcp.run")
    main()
    mock_run.assert_called_once()


def test_main_block(mocker: MockerFixture) -> None:
    import runpy

    mock_run = mocker.patch("mcp.server.fastmcp.FastMCP.run")
    runpy.run_module("mcp_servers.github.server", run_name="__main__")
    mock_run.assert_called_once()


def test_audit_log_decorator(mocker: MockerFixture, tmp_path: pathlib.Path) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.issues.run_gh", return_value="mock issue create"
    )
    result = gh_issue_create(
        IssueCreateArgs(title="My Issue", body="Issue body", repo="owner/repo")
    )
    assert result == "mock issue create"
    mock_run_gh.assert_called_once()
    import sqlite3

    db_path = tmp_path / ".mcp" / "audit.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT timestamp, tool_name, arguments FROM audit_log").fetchall()
    conn.close()
    assert len(rows) == 1
    ts, tool_name, args_json = rows[0]
    assert tool_name == "gh_issue_create"
    args = json.loads(args_json)["args"]
    assert args["repo"] == "owner/repo"
    assert args["title"] == "My Issue"
    assert args["body"] == "Issue body"


def test_audit_log_decorator_exception_in_db(mocker: MockerFixture) -> None:
    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.issues.run_gh", return_value="mock issue create"
    )
    mocker.patch("sqlite3.connect", side_effect=Exception("db error"))
    result = gh_issue_create(
        IssueCreateArgs(title="My Issue", body="Issue body", repo="owner/repo")
    )
    assert result == "mock issue create"
    mock_run_gh.assert_called_once()


def test_audit_log_decorator_non_model_arg(mocker: MockerFixture) -> None:
    from mcp_servers.github.utils import _audit_log

    @_audit_log
    def dummy_tool(my_arg: str) -> str:
        return my_arg + "!"

    result = dummy_tool("hello")
    assert result == "hello!"


def test_ttl_cache_eviction(mocker: MockerFixture) -> None:
    import mcp_servers.github.utils

    mcp_servers.github.utils._CACHE.clear()

    mock_run_gh = mocker.patch(
        "mcp_servers.github.tools.repos.run_gh", return_value="mock repo list"
    )

    # 1. First call sets cache
    mock_time = mocker.patch("mcp_servers.github.utils.time.time", return_value=1000.0)
    gh_repo_list(RepoListArgs(limit=5, owner="owner"))
    assert mock_run_gh.call_count == 1

    # 2. Second call hits cache (time = 1100.0, diff = 100 < 300)
    mock_time.return_value = 1100.0
    gh_repo_list(RepoListArgs(limit=5, owner="owner"))
    assert mock_run_gh.call_count == 1

    # 3. Third call is after 300s, so it should evict and call again
    mock_time.return_value = 1400.0
    gh_repo_list(RepoListArgs(limit=5, owner="owner"))
    assert mock_run_gh.call_count == 2


def test_audit_log_unserializable_arg(mocker: MockerFixture, tmp_path: pathlib.Path) -> None:
    from mcp_servers.github.utils import _audit_log

    class UnserializableObject:
        pass

    @_audit_log
    def dummy_tool(arg1: object) -> str:
        return "done"

    # Should not raise TypeError during json.dumps
    result = dummy_tool(UnserializableObject())
    assert result == "done"
