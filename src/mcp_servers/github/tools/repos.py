from __future__ import annotations

from mcp_servers._common import run_gh, validate_repo

from ..models.schemas import RepoGetArgs, RepoListArgs
from ..utils import _ttl_cache

_REPO_FIELDS = (
    "name,nameWithOwner,description,url,isPrivate,isArchived,pushedAt,updatedAt,"
    "stargazerCount,forkCount,primaryLanguage"
)


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


@_ttl_cache
def gh_repo_get(args: RepoGetArgs) -> str:
    """Get a single repository's metadata.

    Args:
        repo: Repository as ``owner/name``.
    """
    repo = args.repo
    validate_repo(repo)
    return run_gh(["repo", "view", repo, "--json", _REPO_FIELDS])
