from __future__ import annotations

import json

from mcp_servers.github.client import GhError, gh_request, validate_repo

from ..models.schemas import RepoGetArgs, RepoListArgs
from ..utils import _ttl_cache


@_ttl_cache
async def gh_repo_list(args: RepoListArgs) -> str:
    """List repositories for an owner (user or organization).

    Args:
        owner: The GitHub user or organization name.
        limit: Maximum number of repositories to return (1-100).
    """
    owner = args.owner
    limit = args.limit
    limit = max(1, min(limit, 100))
    params = {"per_page": limit, "sort": "pushed"}
    try:
        # Organizations first — `/orgs/{org}/repos` also returns private repos the App
        # installation can see, which `search/repositories` does not reliably surface.
        resp = await gh_request("GET", f"orgs/{owner}/repos", params=params)
    except GhError as e:
        if e.status_code != 404:
            raise
        resp = await gh_request("GET", f"users/{owner}/repos", params=params)
    items = resp.json()
    results = []
    for r in items:
        results.append(
            {
                "name": r.get("name"),
                "nameWithOwner": r.get("full_name"),
                "description": r.get("description"),
                "url": r.get("html_url"),
                "isPrivate": r.get("private"),
                "isArchived": r.get("archived"),
                "pushedAt": r.get("pushed_at"),
                "updatedAt": r.get("updated_at"),
                "stargazerCount": r.get("stargazers_count"),
                "forkCount": r.get("forks_count"),
                "primaryLanguage": {"name": r.get("language")} if r.get("language") else None,
            }
        )
    return json.dumps(results)


@_ttl_cache
async def gh_repo_get(args: RepoGetArgs) -> str:
    """Get a single repository's metadata.

    Args:
        repo: Repository as ``owner/name``.
    """
    repo = args.repo
    validate_repo(repo)
    resp = await gh_request("GET", f"repos/{repo}")
    r = resp.json()
    result = {
        "name": r.get("name"),
        "nameWithOwner": r.get("full_name"),
        "description": r.get("description"),
        "url": r.get("html_url"),
        "isPrivate": r.get("private"),
        "isArchived": r.get("archived"),
        "pushedAt": r.get("pushed_at"),
        "updatedAt": r.get("updated_at"),
        "stargazerCount": r.get("stargazers_count"),
        "forkCount": r.get("forks_count"),
        "primaryLanguage": {"name": r.get("language")} if r.get("language") else None,
    }
    return json.dumps(result)
