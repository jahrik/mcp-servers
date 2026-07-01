from __future__ import annotations

import re

from mcp_servers._common import run_gh, validate_ref, validate_repo

from ..models.schemas import (
    ApiGetArgs,
    FileGetArgs,
    GraphqlQueryArgs,
    SearchCodeArgs,
    SearchIssuesArgs,
    SearchPrsArgs,
)

_PR_FIELDS = "number,title,state,author,headRefName,baseRefName,isDraft,url,updatedAt"
_ISSUE_FIELDS = "number,title,state,author,labels,url,updatedAt"


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


def gh_graphql_query(args: GraphqlQueryArgs) -> str:
    """Make a read-only GraphQL query to the GitHub API.

    Args:
        query: The GraphQL query string.
        jq_filter: Optional jq filter string to parse the response.
    """
    if re.search(r"^\s*mutation\b", args.query, re.IGNORECASE):
        raise ValueError("Mutations are not allowed in gh_graphql_query")
    query = args.query
    jq_filter = args.jq_filter
    cmd_args = ["api", "graphql", "-f", f"query={query}"]
    if jq_filter is not None:
        cmd_args += ["--jq", jq_filter]
    return run_gh(cmd_args)
