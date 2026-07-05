import pytest

from mcp_servers.workspace.git import (
    WsError,
    find_repos,
    needs_attention,
    repo_status,
    resolve_repo,
    resolve_root,
    run_git,
)


def test_resolve_root_explicit(workspace):
    assert resolve_root(str(workspace)) == workspace


def test_resolve_root_env(workspace, monkeypatch):
    monkeypatch.setenv("MCP_WORKSPACE_ROOT", str(workspace))
    assert resolve_root(None) == workspace


def test_resolve_root_default_expands_home(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_WORKSPACE_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "github").mkdir()
    assert resolve_root(None) == tmp_path / "github"


def test_resolve_root_missing_raises(tmp_path):
    with pytest.raises(WsError, match="not a directory"):
        resolve_root(str(tmp_path / "nope"))


def test_resolve_repo_relative_to_root(workspace):
    assert resolve_repo("clean", str(workspace)) == workspace / "clean"


def test_resolve_repo_absolute(workspace):
    assert resolve_repo(str(workspace / "clean")) == workspace / "clean"


def test_resolve_repo_not_a_repo(workspace):
    with pytest.raises(WsError, match="not a git repository"):
        resolve_repo("not-a-repo", str(workspace))


def test_find_repos_skips_non_repos(workspace):
    assert [r.name for r in find_repos(workspace)] == ["clean"]


@pytest.mark.asyncio
async def test_run_git_failure_raises(workspace):
    with pytest.raises(WsError, match="git log failed"):
        await run_git(workspace / "not-a-repo", "log")


@pytest.mark.asyncio
async def test_repo_status_clean_but_no_upstream(workspace):
    status = await repo_status(workspace / "clean")
    assert status["name"] == "clean"
    assert status["branch"] == "main"
    assert status["dirty"] is False
    assert status["upstream"] is None
    # a clean repo with no upstream still needs attention (nothing is pushed)
    assert needs_attention(status)


@pytest.mark.asyncio
async def test_repo_status_dirty_counts(workspace, git):
    repo = workspace / "clean"
    (repo / "README.md").write_text("changed\n")
    (repo / "staged.txt").write_text("staged\n")
    git(repo, "add", "staged.txt")
    (repo / "untracked.txt").write_text("new\n")
    status = await repo_status(repo)
    assert status["staged"] == 1
    assert status["unstaged"] == 1
    assert status["untracked"] == 1
    assert status["dirty"] is True


@pytest.mark.asyncio
async def test_repo_status_ahead_and_stash(workspace, git, make_repo, add_origin):
    repo = make_repo(workspace, "tracked")
    add_origin(repo)
    (repo / "new.txt").write_text("ahead\n")
    git(repo, "add", "new.txt")
    git(repo, "commit", "-m", "ahead commit")
    (repo / "README.md").write_text("stash me\n")
    git(repo, "stash")
    status = await repo_status(repo)
    assert status["upstream"] == "origin/main"
    assert status["ahead"] == 1
    assert status["behind"] == 0
    assert status["stashes"] == 1
    assert needs_attention(status)


@pytest.mark.asyncio
async def test_repo_status_counts_conflicts(workspace, git, make_repo):
    import subprocess

    repo = make_repo(workspace, "conflicted")
    git(repo, "checkout", "-b", "other")
    (repo / "README.md").write_text("theirs\n")
    git(repo, "commit", "-am", "theirs")
    git(repo, "checkout", "main")
    (repo / "README.md").write_text("ours\n")
    git(repo, "commit", "-am", "ours")
    with pytest.raises(subprocess.CalledProcessError):
        git(repo, "merge", "other")
    status = await repo_status(repo)
    assert status["conflicts"] == 1
    assert status["dirty"] is True


@pytest.mark.asyncio
async def test_repo_status_tracked_clean_is_quiet(workspace, make_repo, add_origin):
    repo = make_repo(workspace, "quiet")
    add_origin(repo)
    status = await repo_status(repo)
    assert not needs_attention(status)
