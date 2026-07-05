"""Local git plumbing for the workspace server.

Runs ``git`` as a subprocess with a fixed argv (never through a shell) and
only ever with read-only commands. The server reports on the user's own
working copies; it does not mutate them.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

DEFAULT_ROOT_ENV = "MCP_WORKSPACE_ROOT"
DEFAULT_ROOT = "~/github"


class WsError(Exception):
    """A workspace/git failure with an agent-actionable message."""


async def run_git(repo: Path, *args: str) -> str:
    """Run a read-only git command in ``repo`` and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise WsError(f"git {args[0]} failed in {repo}: {stderr.decode(errors='replace').strip()}")
    return stdout.decode(errors="replace")


def resolve_root(root: str | None) -> Path:
    """Resolve the workspace root (arg > $MCP_WORKSPACE_ROOT > ~/github)."""
    raw = root or os.environ.get(DEFAULT_ROOT_ENV) or DEFAULT_ROOT
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise WsError(
            f"workspace root {path} is not a directory — pass `root` or set ${DEFAULT_ROOT_ENV}"
        )
    return path


def resolve_repo(path: str, root: str | None = None) -> Path:
    """Resolve a single repo path (absolute, ~-relative, or relative to the root)."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = resolve_root(root) / candidate
    candidate = candidate.resolve()
    if not (candidate / ".git").exists():
        raise WsError(f"{candidate} is not a git repository (no .git)")
    return candidate


def find_repos(root: Path) -> list[Path]:
    """Immediate subdirectories of ``root`` that are git repositories."""
    return sorted(d for d in root.iterdir() if d.is_dir() and (d / ".git").exists())


async def repo_status(repo: Path) -> dict[str, object]:
    """Summarize one repo from ``git status --porcelain=v2 --branch``."""
    out = await run_git(repo, "status", "--porcelain=v2", "--branch")
    branch: str | None = None
    upstream: str | None = None
    ahead = behind = staged = unstaged = untracked = conflicts = 0
    for line in out.splitlines():
        if line.startswith("# branch.head "):
            branch = line.split(" ", 2)[2]
        elif line.startswith("# branch.upstream "):
            upstream = line.split(" ", 2)[2]
        elif line.startswith("# branch.ab "):
            plus, minus = line.split(" ")[2:4]
            ahead, behind = int(plus), -int(minus)
        elif line.startswith(("1 ", "2 ")):
            xy = line.split(" ")[1]
            if xy[0] != ".":
                staged += 1
            if xy[1] != ".":
                unstaged += 1
        elif line.startswith("? "):
            untracked += 1
        elif line.startswith("u "):
            conflicts += 1
    stashes = len((await run_git(repo, "stash", "list", "--format=%H")).splitlines())
    dirty = bool(staged or unstaged or untracked or conflicts)
    return {
        "name": repo.name,
        "branch": branch,
        "upstream": upstream,
        "ahead": ahead,
        "behind": behind,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicts": conflicts,
        "stashes": stashes,
        "dirty": dirty,
    }


def needs_attention(status: dict[str, object]) -> bool:
    """A repo needs attention if it's dirty, diverged, stashed, or has no upstream."""
    return bool(
        status["dirty"]
        or status["ahead"]
        or status["behind"]
        or status["stashes"]
        or status["upstream"] is None
    )
