from __future__ import annotations

import json
import re

import jq

from mcp_servers.github.client import gh_request, validate_ref, validate_repo

from ..models.schemas import (
    ApiGetArgs,
    ApiGraphqlArgs,
    FileGetArgs,
    SearchCodeArgs,
    SearchIssuesArgs,
    SearchPrsArgs,
)


def _apply_jq(data: str, jq_filter: str) -> str:
    """Run a jq program against a JSON response body, in-process (no `jq` binary)."""
    try:
        value = json.loads(data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Response was not valid JSON; cannot apply --jq: {e}") from e
    try:
        outputs = jq.compile(jq_filter).input_value(value).all()
    except ValueError as e:
        raise ValueError(f"Invalid jq filter {jq_filter!r}: {e}") from e
    lines = [o if isinstance(o, str) else json.dumps(o) for o in outputs]
    return "\n".join(lines)


async def gh_file_get(args: FileGetArgs) -> str:
    """Read a file's contents from a repo at a given ref."""
    repo = args.repo
    path = args.path
    ref = args.ref
    validate_repo(repo)
    validate_ref(ref)
    resp = await gh_request(
        "GET",
        f"repos/{repo}/contents/{path}",
        params={"ref": ref},
        headers={"Accept": "application/vnd.github.raw+json"},
    )
    return resp.text


async def gh_search_code(args: SearchCodeArgs) -> str:
    """Search code on GitHub."""
    query = args.query
    repo = args.repo
    limit = max(1, min(args.limit, 100))
    if repo is not None:
        validate_repo(repo)
        query = f"{query} repo:{repo}"
    resp = await gh_request("GET", "search/code", params={"q": query, "per_page": limit})
    return json.dumps(resp.json())


async def gh_search_prs(args: SearchPrsArgs) -> str:
    """Search pull requests on GitHub."""
    query = args.query
    repo = args.repo
    limit = max(1, min(args.limit, 100))
    if repo is not None:
        validate_repo(repo)
        query = f"{query} repo:{repo}"
    query += " is:pr"
    resp = await gh_request("GET", "search/issues", params={"q": query, "per_page": limit})
    items = resp.json().get("items", [])
    results = []
    for r in items:
        results.append(
            {
                "number": r.get("number"),
                "title": r.get("title"),
                "state": r.get("state"),
                "author": {"login": r.get("user", {}).get("login")} if r.get("user") else {},
                "url": r.get("html_url"),
                "updatedAt": r.get("updated_at"),
                "isDraft": r.get("draft"),
            }
        )
    return json.dumps(results[:limit])


async def gh_search_issues(args: SearchIssuesArgs) -> str:
    """Search issues on GitHub."""
    query = args.query
    repo = args.repo
    limit = max(1, min(args.limit, 100))
    if repo is not None:
        validate_repo(repo)
        query = f"{query} repo:{repo}"
    query += " is:issue"
    resp = await gh_request("GET", "search/issues", params={"q": query, "per_page": limit})
    items = resp.json().get("items", [])
    results = []
    for r in items:
        results.append(
            {
                "number": r.get("number"),
                "title": r.get("title"),
                "state": r.get("state"),
                "author": {"login": r.get("user", {}).get("login")} if r.get("user") else {},
                "labels": [{"name": lbl.get("name")} for lbl in r.get("labels", [])],
                "url": r.get("html_url"),
                "updatedAt": r.get("updated_at"),
            }
        )
    return json.dumps(results[:limit])


async def gh_api_get(args: ApiGetArgs) -> str:
    """Make a read-only GET request to the GitHub REST API."""
    endpoint = args.endpoint
    if endpoint == "graphql":  # pragma: no cover
        raise ValueError("graphql endpoint is not supported by gh_api_get")
    jq_filter = args.jq_filter
    resp = await gh_request("GET", endpoint)
    data = resp.text
    if jq_filter is not None:
        return _apply_jq(data, jq_filter)
    return data


async def gh_api_graphql(args: ApiGraphqlArgs) -> str:
    """Make a read-only GraphQL query to the GitHub API."""
    if args.query.lstrip().startswith("@"):
        raise ValueError("Query cannot start with '@'")
    if re.search(r"\bmutation\b", args.query, re.IGNORECASE):
        raise ValueError("Mutations are not allowed in gh_api_graphql")
    query = args.query
    jq_filter = args.jq_filter
    payload = {"query": query}
    if args.variables:
        payload["variables"] = args.variables
    resp = await gh_request("POST", "graphql", json=payload)
    data = resp.text
    if jq_filter is not None:
        return _apply_jq(data, jq_filter)
    return data
