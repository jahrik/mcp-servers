import os
import re
import time
from typing import Any

import httpx

from .auth import get_jwt

_TOKEN_CACHE: dict[str, tuple[float, str]] = {}

# Matches the old `gh` CLI subprocess wrapper's DEFAULT_TIMEOUT; httpx's own default
# (5s across connect/read/write/pool) is too tight for things like large CI log downloads.
_TIMEOUT = httpx.Timeout(30.0)


async def get_installation_token() -> str:
    installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")
    if not installation_id:
        raise RuntimeError("GITHUB_APP_INSTALLATION_ID environment variable must be set.")

    now = time.time()
    if "token" in _TOKEN_CACHE:
        timestamp, token = _TOKEN_CACHE["token"]
        # Cache for 50 minutes (3000 seconds)
        if now - timestamp < 3000:
            return token

    jwt_token = get_jwt()
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data = response.json()
        token = data["token"]
        _TOKEN_CACHE["token"] = (now, token)
        return token


class GhError(RuntimeError):
    """Raised when a GitHub API request fails."""

    def __init__(self, message: str, stderr: str = "", status_code: int | None = None):
        super().__init__(message)
        self.stderr = stderr
        self.status_code = status_code


async def gh_request(method: str, endpoint: str, **kwargs: Any) -> httpx.Response:
    """Make an authenticated request to the GitHub API."""
    token = await get_installation_token()

    headers = kwargs.pop("headers", {})
    if "Authorization" not in headers:
        headers["Authorization"] = f"Bearer {token}"
    if "Accept" not in headers:
        headers["Accept"] = "application/vnd.github+json"
    if "X-GitHub-Api-Version" not in headers:
        headers["X-GitHub-Api-Version"] = "2022-11-28"

    # Handle GraphQL vs REST endpoints
    if not endpoint.startswith("http"):
        base_url = "https://api.github.com"
        endpoint = endpoint.lstrip("/")
        url = f"{base_url}/{endpoint}"
    else:
        from urllib.parse import urlparse

        parsed = urlparse(endpoint)
        if parsed.netloc != "api.github.com":
            raise GhError(
                f"Absolute URL host {parsed.netloc!r} is not allowed — "
                "only api.github.com is permitted to prevent token exfiltration."
            )
        url = endpoint

    # follow_redirects: several endpoints (e.g. job logs) 302 to blob storage — httpx
    # doesn't follow redirects by default, which silently truncates those responses.
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = await client.request(method, url, headers=headers, **kwargs)

        if response.is_error:
            # Construct a helpful error message similar to what gh CLI would output
            stderr = response.text
            hint = ""
            if response.status_code == 404:
                hint = "\nHint: Resource not found. Verify repository and arguments."
            elif response.status_code == 422:
                hint = "\nHint: Unprocessable Entity. Validation failed."

            err = GhError(
                f"GitHub API request failed: {response.status_code} {response.reason_phrase}{hint}",
                stderr=stderr,
                status_code=response.status_code,
            )
            raise err

        return response


async def gh_request_paginated(
    method: str,
    endpoint: str,
    *,
    params: dict[str, Any] | None = None,
    max_items: int = 1000,
    **kwargs: Any,
) -> list[Any]:
    """Follow REST `Link: rel="next"` pagination, collecting list results.

    Stops once the response is exhausted or `max_items` have been collected — a safety
    cap, not a page-size setting; each page still requests up to 100 items.
    """
    results: list[Any] = []
    page_params: dict[str, Any] | None = {"per_page": 100, **(params or {})}
    url = endpoint

    while url and len(results) < max_items:
        resp = await gh_request(method, url, params=page_params, **kwargs)
        page_params = None  # the `next` URL already carries the query string
        page = resp.json()
        if not isinstance(page, list):
            raise GhError(
                f"gh_request_paginated: expected a list response from {url!r}, "
                f"got {type(page).__name__}. Use gh_request for non-paginated endpoints."
            )
        results.extend(page)
        next_link = resp.links.get("next")
        url = next_link.get("url") if next_link else None

    return results[:max_items]


_REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")


def validate_repo(repo: str) -> str:
    if not _REPO_RE.match(repo):
        raise GhError(f"Invalid repository {repo!r} — expected 'owner/name'.")
    return repo


def validate_ref(ref: str) -> str:
    if not _REF_RE.match(ref):
        raise GhError(f"Invalid git ref {ref!r}.")
    return ref
