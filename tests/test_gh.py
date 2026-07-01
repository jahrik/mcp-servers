"""Tests for the shared `gh` helpers — pure validation, no network or `gh`."""

from __future__ import annotations

import pytest

from mcp_servers._common import GhError, validate_ref, validate_repo


@pytest.mark.parametrize(
    "repo",
    ["jahrik/ansible-ai-agents", "github/github-mcp-server", "a/b", "Org-1/repo.name_2"],
)
def test_validate_repo_accepts_valid(repo: str) -> None:
    assert validate_repo(repo) == repo


@pytest.mark.parametrize(
    "repo",
    [
        "",
        "no-slash",
        "too/many/slashes",
        "-leading-dash/repo",
        "owner/repo; rm -rf /",
        "owner/repo name",
        "--flag/repo",
    ],
)
def test_validate_repo_rejects_invalid(repo: str) -> None:
    with pytest.raises(GhError):
        validate_repo(repo)


@pytest.mark.parametrize("ref", ["main", "v1.2.3", "release/2026-06", "abc123def"])
def test_validate_ref_accepts_valid(ref: str) -> None:
    assert validate_ref(ref) == ref


@pytest.mark.parametrize("ref", ["", "-x", "a ref", "--upload-pack=evil", "a;b"])
def test_validate_ref_rejects_invalid(ref: str) -> None:
    with pytest.raises(GhError):
        validate_ref(ref)
