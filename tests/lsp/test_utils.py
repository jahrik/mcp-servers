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


def test_safe_exists_swallows_oserror(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    with patch.object(Path, "exists", side_effect=PermissionError):
        assert utils._safe_exists(target) is False


def test_safe_is_file_swallows_oserror(tmp_path):
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    with patch.object(Path, "is_file", side_effect=PermissionError):
        assert utils._safe_is_file(target) is False


def test_prepare_file_absolute_exists_oserror(tmp_path):
    # An unreadable absolute path resolves to "File not found" instead of
    # raising and bypassing the tool-level error handling.
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    with _patch_root(tmp_path), patch.object(Path, "exists", side_effect=PermissionError):
        result = utils._prepare_file(str(target))
    assert isinstance(result, str)
    assert result.startswith("Error: File not found")


def test_prepare_file_relative_is_file_oserror(tmp_path):
    # An unreadable relative candidate is treated as a non-match, not a crash.
    target = tmp_path / "f.py"
    target.write_text("x = 1\n")
    with _patch_root(tmp_path), patch.object(Path, "is_file", side_effect=PermissionError):
        result = utils._prepare_file("f.py")
    assert isinstance(result, str)
    assert result.startswith("Error: File not found")


def test_prepare_file_absolute_directory(tmp_path):
    sub = tmp_path / "adir"
    sub.mkdir()

    with _patch_root(tmp_path):
        result = utils._prepare_file(str(sub))

    assert isinstance(result, str)
    assert result.startswith("Error: Not a regular file")


def test_prepare_file_relative_directory_not_matched(tmp_path):
    # A relative path that resolves to a directory is not a valid match and
    # falls through to the not-found message rather than being returned.
    (tmp_path / "adir").mkdir()

    with _patch_root(tmp_path):
        result = utils._prepare_file("adir")

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


def test_symbol_kind_name_known_and_unknown():
    assert utils._symbol_kind_name(5) == "Class"
    assert utils._symbol_kind_name(12) == "Function"
    assert utils._symbol_kind_name(999) == "Kind999"


def test_symbol_location_symbolinformation():
    sym = {
        "location": {
            "uri": "file:///repo/mod.py",
            "range": {"start": {"line": 9, "character": 4}},
        }
    }
    assert utils._symbol_location(sym) == "/repo/mod.py:10:4"


def test_symbol_location_callhierarchy_item():
    item = {"uri": "file:///repo/mod.py", "range": {"start": {"line": 0, "character": 0}}}
    assert utils._symbol_location(item) == "/repo/mod.py:1:0"


def test_symbol_location_documentsymbol_file_local():
    sym = {"selectionRange": {"start": {"line": 2, "character": 8}}}
    assert utils._symbol_location(sym) == ":3:8"


def test_symbol_location_empty():
    assert utils._symbol_location({"name": "x"}) == ""


def test_format_symbols_flat_with_container():
    symbols = [
        {
            "name": "helper",
            "kind": 12,
            "location": {
                "uri": "file:///repo/mod.py",
                "range": {"start": {"line": 4, "character": 0}},
            },
            "containerName": "Outer",
        }
    ]
    lines = utils._format_symbols(symbols)
    assert lines == ["Function helper  /repo/mod.py:5:0  [Outer]"]


def test_format_symbols_nested_children():
    symbols = [
        {
            "name": "Widget",
            "kind": 5,
            "selectionRange": {"start": {"line": 0, "character": 6}},
            "children": [
                {
                    "name": "render",
                    "kind": 6,
                    "selectionRange": {"start": {"line": 1, "character": 8}},
                }
            ],
        }
    ]
    lines = utils._format_symbols(symbols)
    assert lines == ["Class Widget  :1:6", "  Method render  :2:8"]


def test_format_symbols_skips_non_dict():
    assert utils._format_symbols(["not-a-dict", 42]) == []


def test_filter_symbols():
    symbols = [
        "not-a-dict",  # covers line 225
        {
            "name": "Widget",
            "kind": 5,  # Class
            "selectionRange": {"start": {"line": 0, "character": 6}},
            "children": [
                {
                    "name": "render",
                    "kind": 6,  # Method
                    "selectionRange": {"start": {"line": 1, "character": 8}},
                },
                {
                    "name": "x",
                    "kind": 13,  # Variable
                    "selectionRange": {"start": {"line": 2, "character": 8}},
                },
            ],
        },
    ]
    # Test filtering kinds (e.g. only Method)
    res_kinds = utils._filter_symbols(symbols, kinds=["Method"])
    # Class widget is kept because it contains method render, but Variable x is stripped
    assert len(res_kinds) == 1
    assert res_kinds[0]["name"] == "Widget"
    assert len(res_kinds[0]["children"]) == 1
    assert res_kinds[0]["children"][0]["name"] == "render"

    # Test recursion when matching kind (covers line 242)
    res_recurse = utils._filter_symbols(symbols, kinds=["Class", "Method"])
    assert len(res_recurse) == 1
    assert res_recurse[0]["name"] == "Widget"
    assert len(res_recurse[0]["children"]) == 1
    assert res_recurse[0]["children"][0]["name"] == "render"

    # Test top_level constraint
    res_top = utils._filter_symbols(symbols, top_level=True)
    assert len(res_top) == 1
    assert "children" not in res_top[0]


def test_cap_and_spill():
    # Under limit
    lines = ["a", "b"]
    res = utils._cap_and_spill(
        [{"name": "a"}, {"name": "b"}], [{"name": "a"}, {"name": "b"}], lines, max_n=5
    )
    assert res == "a\nb"

    # Over limit
    results = [{"name": f"item{i}"} for i in range(10)]
    formatted = [f"item{i}" for i in range(10)]
    res_spill = utils._cap_and_spill(results, results, formatted, max_n=3)
    assert "item0" in res_spill
    assert "item1" in res_spill
    assert "item2" in res_spill
    assert "item3" not in res_spill
    assert "... 7 more" in res_spill
    assert "[Spilled full results to: " in res_spill
    assert ".jsonl" in res_spill

    # Assert POSIX path is used in DuckDB query suggestion (no backslashes)
    import re

    match = re.search(r"read_json_auto\('([^']+)'\)", res_spill)
    assert match is not None
    assert "\\" not in match.group(1)

    # Over limit with header lines (which do not count toward max_n)
    res_hdr = utils._cap_and_spill(
        results, results, ["# header1", "item0", "item1", "# header2", "item2"], max_n=3
    )
    assert "# header1" in res_hdr
    assert "# header2" in res_hdr
    assert "item2" in res_hdr
    assert "... 7 more" in res_hdr

    # Spill exception handling (covers lines 285-287)
    with patch("tempfile.NamedTemporaryFile", side_effect=Exception("spill error")):
        res_err = utils._cap_and_spill(results, results, formatted, max_n=3)
        assert "[Error: Failed to write full spill file: spill error]" in res_err
