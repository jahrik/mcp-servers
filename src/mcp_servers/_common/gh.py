"""Safe wrapper around the GitHub CLI (`gh`).

Every server in this repo shells out to `gh` rather than hitting the GitHub API
directly. That means the servers inherit the user's existing `gh auth login`
session (the token `gh` keeps in the system keyring) — no Personal Access Token,
no secret in any config file, no OAuth dance.

Security: model-supplied values reach `gh` only as elements of an argv list
(never a shell string), so there is no shell-injection surface. On top of that,
`validate_repo`/`validate_ref` reject obviously malformed input before it is ever
passed as an argument, so a value can't masquerade as a flag.
"""

from __future__ import annotations

import re
import shutil
import subprocess

# owner/name — GitHub login and repo name character sets.
_REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")
# Branch / tag / sha — conservative; no leading dash, no whitespace or shell meta.
_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}$")

# How long any single `gh` invocation may run before we give up.
DEFAULT_TIMEOUT = 30


class GhError(RuntimeError):
    """Raised when the `gh` CLI is missing or a command fails."""


def validate_repo(repo: str) -> str:
    """Return `repo` if it is a well-formed ``owner/name`` slug, else raise."""
    if not _REPO_RE.match(repo):
        raise GhError(f"Invalid repository {repo!r} — expected 'owner/name'.")
    return repo


def validate_ref(ref: str) -> str:
    """Return `ref` if it is a plausible branch/tag/sha, else raise."""
    if not _REF_RE.match(ref):
        raise GhError(f"Invalid git ref {ref!r}.")
    return ref


def run_gh(args: list[str], *, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Run ``gh`` with `args` (an argv list) and return stdout.

    Raises `GhError` if `gh` is not installed, the call times out, or it exits
    non-zero (the error carries `gh`'s stderr so the model sees why).
    """
    if shutil.which("gh") is None:
        raise GhError(
            "The GitHub CLI (`gh`) is not installed or not on PATH. "
            "Install it and run `gh auth login`."
        )
    try:
        proc = subprocess.run(  # noqa: S603 — argv list, no shell, trusted binary
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GhError(f"`gh {' '.join(args)}` timed out after {timeout}s.") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.strip() or proc.stdout.strip() or "(no output)"
        hint = ""
        stderr_lower = stderr.lower()
        if "could not resolve to a repository" in stderr_lower or "not found" in stderr_lower:
            if "could not resolve to a repository" in stderr_lower:
                hint = (
                    "\nHint: Repository not found. Use gh_repo_list to find the correct "
                    "repository name."
                )
            elif "branch" in stderr_lower or "revision" in stderr_lower:
                hint = (
                    "\nHint: Branch or ref not found. Use gh_repo_get or "
                    "gh_run_list to verify branches/refs."
                )
            else:
                hint = "\nHint: Resource not found. Verify repository and arguments."
        elif "is not mergeable" in stderr:
            hint = (
                "\nHint: PR is not mergeable. Check gh_pr_checks for failures or "
                "gh_pr_diff for conflicts."
            )
        elif "could not resolve to a node" in stderr_lower:
            hint = "\nHint: Thread or comment not found, or not resolvable. Verify the thread ID."

        raise GhError(f"`gh {' '.join(args)}` failed: {stderr}{hint}")

    return proc.stdout
