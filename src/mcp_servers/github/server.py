"""A small, curated GitHub MCP server.

Exposes the handful of operations an agent actually reaches for during code
work — reads plus a narrow set of writes — rather than the full GitHub API
surface. Every tool shells out to `gh`, so it authenticates with your existing
`gh auth login` session and needs no token.

Writes are added deliberately, one tool at a time (currently the PR review-thread
loop: reply, resolve). The server never merges a PR or pushes to a default
branch — those stay out by design.
"""

from __future__ import annotations

import functools
import inspect
import json
import os
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from mcp.server.fastmcp import FastMCP

from mcp_servers._common import run_gh, validate_ref, validate_repo

from .models import (
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

mcp = FastMCP("github")

# JSON field sets kept small so tool output stays readable in-context.
_PR_FIELDS = "number,title,state,author,headRefName,baseRefName,isDraft,url,updatedAt"
_ISSUE_FIELDS = "number,title,state,author,labels,url,updatedAt"
_RUN_FIELDS = "databaseId,name,displayTitle,status,conclusion,headBranch,headSha,url,updatedAt"
_CHECK_FIELDS = "name,state,bucket,startedAt,completedAt,link,description,workflow"
_REPO_FIELDS = (
    "name,nameWithOwner,description,url,isPrivate,isArchived,pushedAt,updatedAt,"
    "stargazerCount,forkCount,primaryLanguage"
)


_CACHE: dict[str, tuple[float, Any]] = {}


def _ttl_cache(func: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(func)
    def wrapper(args: Any) -> Any:
        if getattr(args, "no_cache", False):
            return func(args)
        dump_args = {}
        if hasattr(args, "model_dump"):
            dump_args = args.model_dump(exclude={"no_cache"} if hasattr(args, "no_cache") else None)
        key = f"{getattr(func, '__name__', str(func))}:{json.dumps(dump_args, sort_keys=True)}"
        now = time.time()
        if key in _CACHE:
            timestamp, value = _CACHE[key]
            if now - timestamp < 300:
                return value
        result = func(args)
        _CACHE[key] = (now, result)
        return result

    return wrapper


def _audit_log[F: Callable[..., Any]](func: F) -> F:
    """Decorator to audit log write tools to a SQLite DB."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()

        dumped_args = {}
        for k, v in bound.arguments.items():
            if hasattr(v, "model_dump"):
                dumped_args[k] = v.model_dump()
            else:
                dumped_args[k] = v
        args_json = json.dumps(dumped_args)

        start_time = datetime.now(UTC)
        success = True
        stderr = None

        try:
            return func(*args, **kwargs)
        except Exception as e:
            success = False
            from mcp_servers._common.gh import GhError

            stderr = str(e) if isinstance(e, GhError) else repr(e)
            raise
        finally:
            end_time = datetime.now(UTC)
            duration_ms = (end_time - start_time).total_seconds() * 1000

            try:
                mcp_dir = os.path.expanduser("~/.mcp")
                os.makedirs(mcp_dir, exist_ok=True)
                db_path = os.path.join(mcp_dir, "audit.db")

                conn = sqlite3.connect(db_path)
                try:
                    with conn:
                        conn.execute(
                            """CREATE TABLE IF NOT EXISTS audit_log (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                timestamp TEXT,
                                tool_name TEXT,
                                arguments TEXT,
                                duration_ms REAL,
                                success BOOLEAN,
                                stderr TEXT
                            )"""
                        )
                        # Migrations for existing DBs
                        import contextlib

                        for col, col_type in [
                            ("duration_ms", "REAL"),
                            ("success", "BOOLEAN"),
                            ("stderr", "TEXT"),
                        ]:
                            with contextlib.suppress(sqlite3.OperationalError):
                                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {col_type}")

                        ts = start_time.isoformat()
                        conn.execute(
                            "INSERT INTO audit_log (timestamp, tool_name, arguments, "
                            "duration_ms, success, stderr) VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                ts,
                                getattr(func, "__name__", str(func)),
                                args_json,
                                duration_ms,
                                success,
                                stderr,
                            ),
                        )
                finally:
                    conn.close()
            except Exception:
                pass

    return cast(F, wrapper)


@mcp.tool()
@_ttl_cache
def gh_repo_list(args: RepoListArgs) -> str:
    """List repositories for an owner (user or organization).

    Args:
        owner: The GitHub user or organization name.
        limit: Maximum number of repositories to return (1-100).
    """
    owner = args.owner
    limit = args.limit
    limit = max(1, min(limit, 100))
    return run_gh(["repo", "list", owner, "--limit", str(limit), "--json", _REPO_FIELDS])


@mcp.tool()
@_ttl_cache
def gh_repo_get(args: RepoGetArgs) -> str:
    """Get a single repository's metadata.

    Args:
        repo: Repository as ``owner/name``.
    """
    repo = args.repo
    validate_repo(repo)
    return run_gh(["repo", "view", repo, "--json", _REPO_FIELDS])


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def gh_pr_diff(args: PrArgs) -> str:
    """Get the unified diff for a pull request."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    return run_gh(["pr", "diff", str(int(number)), "-R", repo])


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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
    if merge_method not in {"squash", "merge", "rebase"}:
        raise ValueError(f"Invalid merge method: {merge_method}")
    cmd_args = ["pr", "merge", str(int(pr)), "-R", repo, f"--{merge_method}"]
    if delete_branch:
        cmd_args += ["--delete-branch"]
    return run_gh(cmd_args)


@mcp.tool()
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


@mcp.tool()
def gh_issue_get(args: IssueArgs) -> str:
    """Get a single issue's metadata and body."""
    repo = args.repo
    number = args.number
    validate_repo(repo)
    return run_gh(
        ["issue", "view", str(int(number)), "-R", repo, "--json", f"{_ISSUE_FIELDS},body,comments"]
    )


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
def gh_file_get(args: FileGetArgs) -> str:
    """Read a file's contents from a repo at a given ref.

    Args:
        repo: Repository as ``owner/name``.
        path: Path to the file within the repo.
        ref: Branch, tag, or commit SHA (default ``HEAD``).
    """
    repo = args.repo
    path = args.path
    ref = args.ref
    validate_repo(repo)
    validate_ref(ref)
    # `gh api` with a raw Accept header returns the file body verbatim.
    return run_gh(
        [
            "api",
            f"repos/{repo}/contents/{path}",
            "-f",
            f"ref={ref}",
            "-H",
            "Accept: application/vnd.github.raw+json",
        ]
    )


@mcp.tool()
def gh_search_code(args: SearchCodeArgs) -> str:
    """Search code on GitHub.

    Args:
        query: Search expression (GitHub code-search syntax).
        repo: Optional ``owner/name`` to scope the search to one repo.
        limit: Maximum number of results (1-100).
    """
    query = args.query
    repo = args.repo
    limit = args.limit
    limit = max(1, min(limit, 100))
    cmd_args = ["search", "code", query, "--limit", str(limit)]
    if repo is not None:
        validate_repo(repo)
        cmd_args += ["--repo", repo]
    return run_gh(cmd_args)


@mcp.tool()
def gh_search_prs(args: SearchPrsArgs) -> str:
    """Search pull requests on GitHub.

    Args:
        query: Search expression (GitHub search syntax).
        repo: Optional ``owner/name`` to scope the search to one repo.
        limit: Maximum number of results (1-100).
    """
    query = args.query
    repo = args.repo
    limit = args.limit
    limit = max(1, min(limit, 100))
    cmd_args = ["search", "prs", query, "--limit", str(limit), "--json", _PR_FIELDS]
    if repo is not None:
        validate_repo(repo)
        cmd_args += ["--repo", repo]
    return run_gh(cmd_args)


@mcp.tool()
def gh_search_issues(args: SearchIssuesArgs) -> str:
    """Search issues on GitHub.

    Args:
        query: Search expression (GitHub search syntax).
        repo: Optional ``owner/name`` to scope the search to one repo.
        limit: Maximum number of results (1-100).
    """
    query = args.query
    repo = args.repo
    limit = args.limit
    limit = max(1, min(limit, 100))
    cmd_args = ["search", "issues", query, "--limit", str(limit), "--json", _ISSUE_FIELDS]
    if repo is not None:
        validate_repo(repo)
        cmd_args += ["--repo", repo]
    return run_gh(cmd_args)


# --- Actions / CI ------------------------------------------------------------


@mcp.tool()
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


@mcp.tool()
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


@mcp.tool()
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


# --- Review threads: read -> reply -> resolve --------------------------------
# The review loop (handle Copilot's inline comments on a PR): read the comments,
# reply to one, mark its thread resolved. Replies use REST; reading threads and
# resolving them need GraphQL (REST can't resolve a thread). `resolve` needs a
# thread node id, which the caller gets from `gh_review_threads_get` — so the four
# tools are one read -> respond -> resolve loop.

# Project the inline-comment fields the review loop actually needs, so output
# stays lean (raw `gh api` comment objects carry dozens of fields).
_REVIEW_COMMENT_PROJECT = "{id, author: .user.login, path, line: (.line // .original_line), body}"

# A comment counts as a bot comment when its author is a GitHub App/bot or its
# login contains "copilot" — the actionable comments in an automated review.
# `.user.type` is the REST field; `.author.__typename` the GraphQL one.
_BOT_SELECT_REST = (
    'select(.user.type == "Bot" or (.user.login | ascii_downcase | contains("copilot")))'
)
_BOT_THREAD_JQ = (
    ".data.repository.pullRequest.reviewThreads.nodes |= "
    "map(select(any(.comments.nodes[]; "
    '.author.__typename == "Bot" or (.author.login | ascii_downcase | contains("copilot")))))'
)


def _review_comment_jq(*, bot_only: bool) -> str:
    """`gh api --jq` program that projects (and optionally bot-filters) comments."""
    stages = [".[]"]
    if bot_only:
        stages.append(_BOT_SELECT_REST)
    stages.append(_REVIEW_COMMENT_PROJECT)
    return " | ".join(stages)


# Read every review thread on a PR with its node id (needed to resolve), its
# resolved/outdated state, and the comments it contains (databaseId ties a
# thread back to a REST comment id from `gh_review_comments_list`; __typename lets
# `bot_only` keep only threads with a bot comment).
_THREADS_QUERY = """
query($owner:String!,$name:String!,$pr:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$pr){
      reviewThreads(first:100){
        nodes{
          id
          isResolved
          isOutdated
          comments(first:100){
            nodes{ databaseId author{login __typename} path line body }
          }
        }
      }
    }
  }
}
"""

_RESOLVE_MUTATION = """
mutation($threadId:ID!){
  resolveReviewThread(input:{threadId:$threadId}){ thread{ id isResolved } }
}
"""


@mcp.tool()
def gh_review_comments_list(args: ReviewCommentsListArgs) -> str:
    """List a PR's inline review comments (read-only).

    Returns one JSON object per comment with the ``id`` (needed to reply),
    author, ``path``, ``line``, and body.

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        bot_only: Keep only bot/Copilot comments — the actionable ones in an
            automated review.
    """
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    validate_repo(repo)
    return run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{int(pr)}/comments",
            "--paginate",
            "--jq",
            _review_comment_jq(bot_only=bot_only),
        ]
    )


@mcp.tool()
def gh_review_threads_get(args: ReviewThreadsGetArgs) -> str:
    """List a PR's review threads with ids and resolved state (read-only).

    Each thread carries its node ``id`` (pass to ``gh_review_thread_resolve``), its
    ``isResolved``/``isOutdated`` state, and the comments in it (each with a
    ``databaseId`` matching a ``gh_review_comments_list`` id).

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        bot_only: Keep only threads that contain a bot/Copilot comment.
    """
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    validate_repo(repo)
    owner, _, name = repo.partition("/")
    cmd_args = [
        "api",
        "graphql",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"pr={int(pr)}",
        "-f",
        f"query={_THREADS_QUERY}",
    ]
    if bot_only:
        # Filter thread nodes in place, preserving the response envelope.
        cmd_args += ["--jq", _BOT_THREAD_JQ]
    return run_gh(cmd_args)


@mcp.tool()
@_audit_log
def gh_review_comment_reply(args: ReviewCommentReplyArgs) -> str:
    """Reply to a PR inline review comment's thread (write).

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        comment_id: The review comment id to reply to (from
            ``gh_review_comments_list``).
        body: Reply text.
    """
    repo = args.repo
    pr = args.pr
    comment_id = args.comment_id
    body = args.body
    validate_repo(repo)
    return run_gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/pulls/{int(pr)}/comments/{int(comment_id)}/replies",
            "-f",
            f"body={body}",
        ]
    )


@mcp.tool()
@_audit_log
def gh_review_thread_resolve(args: ReviewThreadResolveArgs) -> str:
    """Resolve a PR review thread by its node id (write).

    Args:
        thread_id: The review thread node id from ``gh_review_threads_get``.
    """
    thread_id = args.thread_id
    return run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"threadId={thread_id}",
            "-f",
            f"query={_RESOLVE_MUTATION}",
        ]
    )


@mcp.tool()
def gh_api_get(args: ApiGetArgs) -> str:
    """Make a read-only GET request to the GitHub REST API.

    Args:
        endpoint: The API endpoint path (e.g. ``repos/owner/repo/pulls``).
        jq_filter: Optional jq filter string to parse the response.
    """
    endpoint = args.endpoint
    jq_filter = args.jq_filter
    cmd_args = ["api", endpoint]
    if jq_filter is not None:
        cmd_args += ["--jq", jq_filter]
    return run_gh(cmd_args)


@mcp.tool()
def gh_graphql_query(args: GraphqlQueryArgs) -> str:
    """Make a read-only GraphQL query to the GitHub API.

    Args:
        query: The GraphQL query string.
        jq_filter: Optional jq filter string to parse the response.
    """
    if "mutation" in args.query.lower():
        raise ValueError("Mutations are not allowed in gh_graphql_query")
    query = args.query
    jq_filter = args.jq_filter
    cmd_args = ["api", "graphql", "-f", f"query={query}"]
    if jq_filter is not None:
        cmd_args += ["--jq", jq_filter]
    return run_gh(cmd_args)


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
