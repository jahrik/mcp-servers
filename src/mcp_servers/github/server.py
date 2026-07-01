"""A small, read-only GitHub MCP server.

Exposes a curated handful of read operations — the things an agent actually
reaches for during code work — rather than the full GitHub API surface. Every
tool shells out to `gh`, so it authenticates with your existing `gh auth login`
session and needs no token.

Add write operations (open PR, comment) deliberately, as separate tools, if and
when you want them — keeping the default surface read-only is the point.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_servers._common import run_gh, validate_ref, validate_repo

mcp = FastMCP("github")

# JSON field sets kept small so tool output stays readable in-context.
_PR_FIELDS = "number,title,state,author,headRefName,baseRefName,isDraft,url,updatedAt"
_ISSUE_FIELDS = "number,title,state,author,labels,url,updatedAt"


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


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
