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

from mcp.server.fastmcp import FastMCP

from mcp_servers._common import run_gh, validate_ref, validate_repo

mcp = FastMCP("github")

# JSON field sets kept small so tool output stays readable in-context.
_PR_FIELDS = "number,title,state,author,headRefName,baseRefName,isDraft,url,updatedAt"
_ISSUE_FIELDS = "number,title,state,author,labels,url,updatedAt"
_RUN_FIELDS = "databaseId,name,displayTitle,status,conclusion,headBranch,headSha,url,updatedAt"
_CHECK_FIELDS = "name,state,bucket,startedAt,completedAt,link,description,workflow"


@mcp.tool()
def list_prs(repo: str, state: str = "open", limit: int = 20) -> str:
    """List pull requests for a repo.

    Args:
        repo: Repository as ``owner/name``.
        state: ``open``, ``closed``, ``merged``, or ``all``.
        limit: Maximum number of PRs to return (1-100).
    """
    validate_repo(repo)
    limit = max(1, min(limit, 100))
    return run_gh(
        ["pr", "list", "-R", repo, "--state", state, "--limit", str(limit), "--json", _PR_FIELDS]
    )


@mcp.tool()
def get_pr(repo: str, number: int) -> str:
    """Get a single pull request's metadata (title, body, state, refs)."""
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
def pr_diff(repo: str, number: int) -> str:
    """Get the unified diff for a pull request."""
    validate_repo(repo)
    return run_gh(["pr", "diff", str(int(number)), "-R", repo])


@mcp.tool()
def pr_checks(repo: str, number: int) -> str:
    """Get the status of checks for a pull request.

    Args:
        repo: Repository as ``owner/name``.
        number: Pull request number.
    """
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
def list_issues(repo: str, state: str = "open", limit: int = 20) -> str:
    """List issues for a repo.

    Args:
        repo: Repository as ``owner/name``.
        state: ``open``, ``closed``, or ``all``.
        limit: Maximum number of issues to return (1-100).
    """
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
def get_issue(repo: str, number: int) -> str:
    """Get a single issue's metadata and body."""
    validate_repo(repo)
    return run_gh(
        ["issue", "view", str(int(number)), "-R", repo, "--json", f"{_ISSUE_FIELDS},body,comments"]
    )


@mcp.tool()
def get_file(repo: str, path: str, ref: str = "HEAD") -> str:
    """Read a file's contents from a repo at a given ref.

    Args:
        repo: Repository as ``owner/name``.
        path: Path to the file within the repo.
        ref: Branch, tag, or commit SHA (default ``HEAD``).
    """
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
def search_code(query: str, repo: str | None = None, limit: int = 20) -> str:
    """Search code on GitHub.

    Args:
        query: Search expression (GitHub code-search syntax).
        repo: Optional ``owner/name`` to scope the search to one repo.
        limit: Maximum number of results (1-100).
    """
    limit = max(1, min(limit, 100))
    args = ["search", "code", query, "--limit", str(limit)]
    if repo is not None:
        validate_repo(repo)
        args += ["--repo", repo]
    return run_gh(args)


@mcp.tool()
def search_prs(query: str, repo: str | None = None, limit: int = 20) -> str:
    """Search pull requests on GitHub.

    Args:
        query: Search expression (GitHub search syntax).
        repo: Optional ``owner/name`` to scope the search to one repo.
        limit: Maximum number of results (1-100).
    """
    limit = max(1, min(limit, 100))
    args = ["search", "prs", query, "--limit", str(limit), "--json", _PR_FIELDS]
    if repo is not None:
        validate_repo(repo)
        args += ["--repo", repo]
    return run_gh(args)


@mcp.tool()
def search_issues(query: str, repo: str | None = None, limit: int = 20) -> str:
    """Search issues on GitHub.

    Args:
        query: Search expression (GitHub search syntax).
        repo: Optional ``owner/name`` to scope the search to one repo.
        limit: Maximum number of results (1-100).
    """
    limit = max(1, min(limit, 100))
    args = ["search", "issues", query, "--limit", str(limit), "--json", _ISSUE_FIELDS]
    if repo is not None:
        validate_repo(repo)
        args += ["--repo", repo]
    return run_gh(args)


# --- Actions / CI ------------------------------------------------------------


@mcp.tool()
def list_runs(
    repo: str, limit: int = 20, branch: str | None = None, workflow: str | None = None
) -> str:
    """List GitHub Actions workflow runs for a repo.

    Args:
        repo: Repository as ``owner/name``.
        limit: Maximum number of runs to return (1-100).
        branch: Optional branch name to filter by.
        workflow: Optional workflow name or filename to filter by.
    """
    validate_repo(repo)
    limit = max(1, min(limit, 100))
    args = ["run", "list", "-R", repo, "--limit", str(limit), "--json", _RUN_FIELDS]
    if branch is not None:
        args += ["--branch", branch]
    if workflow is not None:
        args += ["--workflow", workflow]
    return run_gh(args)


@mcp.tool()
def get_run(repo: str, run_id: int) -> str:
    """Get details of a specific GitHub Actions workflow run.

    Args:
        repo: Repository as ``owner/name``.
        run_id: The run ID (databaseId).
    """
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
def run_failed_logs(repo: str, run_id: int) -> str:
    """Get the failed logs for a GitHub Actions workflow run.

    Args:
        repo: Repository as ``owner/name``.
        run_id: The run ID (databaseId).
    """
    validate_repo(repo)
    return run_gh(["run", "view", str(int(run_id)), "-R", repo, "--log-failed"])


# --- Review threads: read -> reply -> resolve --------------------------------
# The review loop (handle Copilot's inline comments on a PR): read the comments,
# reply to one, mark its thread resolved. Replies use REST; reading threads and
# resolving them need GraphQL (REST can't resolve a thread). `resolve` needs a
# thread node id, which the caller gets from `get_review_threads` — so the four
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
# thread back to a REST comment id from `list_review_comments`; __typename lets
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
def list_review_comments(repo: str, pr: int, bot_only: bool = False) -> str:
    """List a PR's inline review comments (read-only).

    Returns one JSON object per comment with the ``id`` (needed to reply),
    author, ``path``, ``line``, and body.

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        bot_only: Keep only bot/Copilot comments — the actionable ones in an
            automated review.
    """
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
def get_review_threads(repo: str, pr: int, bot_only: bool = False) -> str:
    """List a PR's review threads with ids and resolved state (read-only).

    Each thread carries its node ``id`` (pass to ``resolve_review_thread``), its
    ``isResolved``/``isOutdated`` state, and the comments in it (each with a
    ``databaseId`` matching a ``list_review_comments`` id).

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        bot_only: Keep only threads that contain a bot/Copilot comment.
    """
    validate_repo(repo)
    owner, _, name = repo.partition("/")
    args = [
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
        args += ["--jq", _BOT_THREAD_JQ]
    return run_gh(args)


@mcp.tool()
def reply_review_comment(repo: str, pr: int, comment_id: int, body: str) -> str:
    """Reply to a PR inline review comment's thread (write).

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        comment_id: The review comment id to reply to (from
            ``list_review_comments``).
        body: Reply text.
    """
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
def resolve_review_thread(thread_id: str) -> str:
    """Resolve a PR review thread by its node id (write).

    Args:
        thread_id: The review thread node id from ``get_review_threads``.
    """
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


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
