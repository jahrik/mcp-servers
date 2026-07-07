from pathlib import Path
from unittest.mock import patch

from mcp_servers.lsp import utils


def _patch_root(root: Path):
    return patch("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(root))


def test_candidate_roots_includes_git_children(tmp_path):
    repo = tmp_path / "repo-a"
    repo.mkdir()
    (repo / ".git").mkdir()
    plain = tmp_path / "not-a-repo"
    plain.mkdir()

    with _patch_root(tmp_path):
        roots = utils._candidate_roots()

    assert roots[0] == tmp_path.resolve()
    assert repo.resolve() in roots
    assert plain.resolve() not in roots


def test_candidate_roots_iterdir_oserror(tmp_path):
    with _patch_root(tmp_path), patch.object(Path, "iterdir", side_effect=OSError):
        roots = utils._candidate_roots()

    assert roots == [tmp_path.resolve()]


def test_candidate_roots_child_oserror_skipped(tmp_path):
    (tmp_path / "repo-a").mkdir()

    with _patch_root(tmp_path), patch.object(Path, "is_dir", side_effect=OSError):
        roots = utils._candidate_roots()

    # The unreadable child is skipped; only the workspace root remains.
    assert roots == [tmp_path.resolve()]


def test_prepare_file_absolute_ok(tmp_path):
    target = tmp_path / "file.py"
    target.write_text("x = 1\n")

    with _patch_root(tmp_path):
        result = utils._prepare_file(str(target))

    assert result == target.resolve()


def test_prepare_file_absolute_outside_root(tmp_path):
    with _patch_root(tmp_path):
        result = utils._prepare_file("/etc/hosts")

    assert isinstance(result, str)
    assert "must be within the workspace root" in result


def test_prepare_file_absolute_not_found(tmp_path):
    with _patch_root(tmp_path):
        result = utils._prepare_file(str(tmp_path / "missing.py"))

    assert isinstance(result, str)
    assert result.startswith("Error: File not found")


def test_prepare_file_relative_in_child_repo(tmp_path):
    repo = tmp_path / "repo-a"
    (repo / "src").mkdir(parents=True)
    (repo / ".git").mkdir()
    target = repo / "src" / "mod.py"
    target.write_text("y = 2\n")

    with _patch_root(tmp_path):
        result = utils._prepare_file("src/mod.py")

    assert result == target.resolve()


def test_prepare_file_relative_ambiguous(tmp_path):
    for name in ("repo-a", "repo-b"):
        repo = tmp_path / name
        (repo / "src").mkdir(parents=True)
        (repo / ".git").mkdir()
        (repo / "src" / "mod.py").write_text("z = 3\n")

    with _patch_root(tmp_path):
        result = utils._prepare_file("src/mod.py")

    assert isinstance(result, str)
    assert "Ambiguous filepath" in result
    assert "repo-a" in result
    assert "repo-b" in result


def test_prepare_file_relative_escapes_root(tmp_path):
    # A ".." traversal resolves outside the workspace root and is rejected by
    # the containment guard rather than being treated as a match.
    with _patch_root(tmp_path):
        result = utils._prepare_file("../outside.py")

    assert isinstance(result, str)
    assert result.startswith("Error: File not found")


def test_prepare_file_relative_not_found(tmp_path):
    with _patch_root(tmp_path):
        result = utils._prepare_file("nope/missing.py")

    assert isinstance(result, str)
    assert result.startswith("Error: File not found")


def test_prepare_file_relative_in_workspace_root(tmp_path):
    target = tmp_path / "top.py"
    target.write_text("w = 4\n")

    with _patch_root(tmp_path):
        result = utils._prepare_file("top.py")

    assert result == target.resolve()
