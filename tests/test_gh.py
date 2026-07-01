"""Tests for the shared `gh` helpers — pure validation, no network or `gh`."""

from __future__ import annotations

import subprocess

import pytest
from pytest_mock import MockerFixture

from mcp_servers._common import GhError, run_gh, validate_ref, validate_repo


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


def test_run_gh_missing_binary(mocker: MockerFixture) -> None:
    mocker.patch("shutil.which", return_value=None)
    with pytest.raises(GhError, match="not installed or not on PATH"):
        run_gh(["list"])


def test_run_gh_timeout(mocker: MockerFixture) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/gh")
    mocker.patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["gh", "list"], timeout=30),
    )
    with pytest.raises(GhError, match="timed out"):
        run_gh(["list"])


def test_run_gh_error_exit(mocker: MockerFixture) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/gh")
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["gh", "list"], returncode=1, stdout="", stderr="some error"
        ),
    )
    with pytest.raises(GhError, match="failed: some error"):
        run_gh(["list"])


def test_run_gh_success(mocker: MockerFixture) -> None:
    mocker.patch("shutil.which", return_value="/usr/bin/gh")
    mocker.patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["gh", "list"], returncode=0, stdout="success output", stderr=""
        ),
    )
    assert run_gh(["list"]) == "success output"
