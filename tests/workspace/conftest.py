from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(repo: Path, *args: str) -> str:
    """Run git synchronously in test setup (never through a shell)."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _make_repo(root: Path, name: str) -> Path:
    """Create a repo with one commit on ``main``."""
    repo = root / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _add_origin(repo: Path, bare_root: Path) -> Path:
    """Give ``repo`` a bare origin with main pushed, tracked, and HEAD recorded."""
    bare = bare_root / f"{repo.name}-origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], capture_output=True, check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-u", "origin", "main")
    _git(repo, "remote", "set-head", "origin", "main")
    return bare


@pytest.fixture
def git():
    return _git


@pytest.fixture
def make_repo():
    return _make_repo


@pytest.fixture
def add_origin(tmp_path: Path):
    def _add(repo: Path) -> Path:
        return _add_origin(repo, tmp_path)

    return _add


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace root containing one clean repo named ``clean``."""
    root = tmp_path / "ws"
    root.mkdir()
    _make_repo(root, "clean")
    (root / "not-a-repo").mkdir()
    return root
