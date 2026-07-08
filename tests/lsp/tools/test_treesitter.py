from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from mcp_servers.lsp.treesitter import (
    detect_language,
    extract_nodes,
    get_outline,
    get_scope_at_position,
    parse_file,
    run_query,
)

PYTHON_SOURCE = """\
class Greeter:
    def greet(self, name: str) -> str:
        return f"Hello, {name}"

def standalone(x: int) -> int:
    if x > 0:
        return x
    return -x
"""

GO_SOURCE = """\
package main

type Server struct {
    port int
}

func (s *Server) Start() error {
    return nil
}

func main() {
    s := &Server{port: 8080}
    s.Start()
}
"""


@pytest.fixture
def python_file(tmp_path):
    f = tmp_path / "example.py"
    f.write_text(PYTHON_SOURCE)
    return f


@pytest.fixture
def go_file(tmp_path):
    f = tmp_path / "main.go"
    f.write_text(GO_SOURCE)
    return f


class TestDetectLanguage:
    @pytest.mark.parametrize(
        ("suffix", "expected"),
        [
            (".py", "python"),
            (".go", "go"),
            (".rs", "rust"),
            (".ts", "typescript"),
            (".tsx", "tsx"),
            (".js", "javascript"),
            (".jsx", "javascript"),
            (".txt", None),
        ],
    )
    def test_extension_mapping(self, suffix, expected):
        assert detect_language(Path(f"file{suffix}")) == expected


class TestParseFile:
    def test_parse_python(self, python_file):
        tree, lang = parse_file(python_file)
        assert lang == "python"
        assert tree.root_node.type == "module"
        assert tree.root_node.child_count > 0

    def test_parse_go(self, go_file):
        tree, lang = parse_file(go_file)
        assert lang == "go"
        assert tree.root_node.type == "source_file"

    def test_parse_with_language_override(self, python_file):
        tree, lang = parse_file(python_file, language="python")
        assert lang == "python"

    def test_parse_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b,c")
        with pytest.raises(ValueError, match="Cannot detect language"):
            parse_file(f)

    def test_parse_unsupported_language(self, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("x = 1")
        with pytest.raises(ValueError, match="Unsupported language"):
            parse_file(f, language="haskell")


class TestRunQuery:
    def test_find_function_names(self, python_file):
        tree, lang = parse_file(python_file)
        results = run_query(tree, lang, "(function_definition name: (identifier) @name)")
        names = [r["text"] for r in results]
        assert "greet" in names
        assert "standalone" in names

    def test_find_class_names(self, python_file):
        tree, lang = parse_file(python_file)
        results = run_query(tree, lang, "(class_definition name: (identifier) @name)")
        names = [r["text"] for r in results]
        assert names == ["Greeter"]

    def test_captures_include_position(self, python_file):
        tree, lang = parse_file(python_file)
        results = run_query(tree, lang, "(class_definition name: (identifier) @name)")
        assert results[0]["start_line"] == 1
        assert results[0]["capture"] == "name"
        assert results[0]["type"] == "identifier"

    def test_no_matches(self, python_file):
        tree, lang = parse_file(python_file)
        results = run_query(tree, lang, "(while_statement) @loop")
        assert results == []

    def test_max_results_cap(self, python_file):
        tree, lang = parse_file(python_file)
        results = run_query(tree, lang, "(identifier) @id", max_results=2)
        assert len(results) == 2

    def test_go_query(self, go_file):
        tree, lang = parse_file(go_file)
        results = run_query(tree, lang, "(function_declaration name: (identifier) @name)")
        names = [r["text"] for r in results]
        assert "main" in names


class TestGetOutline:
    def test_python_outline(self, python_file):
        tree, lang = parse_file(python_file)
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert "Greeter" in names
        assert "greet" in names
        assert "standalone" in names

    def test_outline_has_positions(self, python_file):
        tree, lang = parse_file(python_file)
        symbols = get_outline(tree, lang)
        greeter = next(s for s in symbols if s["name"] == "Greeter")
        assert greeter["kind"] == "class"
        assert greeter["start_line"] == 1
        assert greeter["end_line"] == 3

    def test_go_outline(self, go_file):
        tree, lang = parse_file(go_file)
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert "Server" in names
        assert "Start" in names
        assert "main" in names

    def test_outline_kinds(self, python_file):
        tree, lang = parse_file(python_file)
        symbols = get_outline(tree, lang)
        kinds = {s["name"]: s["kind"] for s in symbols}
        assert kinds["Greeter"] == "class"
        assert kinds["standalone"] == "function"


class TestGetScopeAtPosition:
    def test_inside_method(self, python_file):
        tree, lang = parse_file(python_file)
        scopes = get_scope_at_position(tree, lang, 2, 8)
        types = [s["type"] for s in scopes]
        assert "module" in types
        assert "class_definition" in types
        assert "function_definition" in types

    def test_scope_names(self, python_file):
        tree, lang = parse_file(python_file)
        scopes = get_scope_at_position(tree, lang, 2, 8)
        names = [s["name"] for s in scopes if s["name"]]
        assert "Greeter" in names
        assert "greet" in names

    def test_module_level(self, python_file):
        tree, lang = parse_file(python_file)
        scopes = get_scope_at_position(tree, lang, 0, 0)
        assert scopes[0]["type"] == "module"

    def test_module_end_line_not_inflated_by_trailing_newline(self, tmp_path):
        """The module range must not overshoot when the file ends with a newline."""
        f = tmp_path / "trailing.py"
        f.write_text("def a():\n    return 1\ndef b():\n    return 2\n")  # 4 lines + newline
        tree, lang = parse_file(f)
        scopes = get_scope_at_position(tree, lang, 2, 0)
        module = next(s for s in scopes if s["type"] == "module")
        assert module["start_line"] == 1
        assert module["end_line"] == 4

    def test_module_end_line_without_trailing_newline(self, tmp_path):
        """No trailing newline was already correct; keep it correct."""
        f = tmp_path / "no_trailing.py"
        f.write_text("def a():\n    return 1\ndef b():\n    return 2")  # 4 lines, no newline
        tree, lang = parse_file(f)
        scopes = get_scope_at_position(tree, lang, 2, 0)
        module = next(s for s in scopes if s["type"] == "module")
        assert module["end_line"] == 4

    def test_standalone_function(self, python_file):
        tree, lang = parse_file(python_file)
        scopes = get_scope_at_position(tree, lang, 5, 4)
        names = [s["name"] for s in scopes if s["name"]]
        assert "standalone" in names
        assert "Greeter" not in names


class TestExtractNodes:
    def test_extract_function(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        results = extract_nodes(tree, lang, source, "function_definition", "standalone")
        assert len(results) == 1
        result = results[0]
        assert "def standalone" in result["text"]
        assert "return -x" in result["text"]
        assert result["start_line"] == 5
        assert result["end_line"] == 8

    def test_extract_class(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        results = extract_nodes(tree, lang, source, "class_definition", "Greeter")
        assert len(results) == 1
        assert "class Greeter" in results[0]["text"]
        assert "def greet" in results[0]["text"]

    def test_extract_not_found(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        results = extract_nodes(tree, lang, source, "function_definition", "nonexistent")
        assert results == []

    def test_extract_returns_all_ambiguous_matches(self, tmp_path):
        """A name shared by several nodes yields every match, not just the first."""
        f = tmp_path / "dup.py"
        f.write_text(
            "class A:\n"
            "    def __init__(self):\n"
            "        self.a = 1\n"
            "\n"
            "class B:\n"
            "    def __init__(self):\n"
            "        self.b = 2\n"
        )
        tree, lang = parse_file(f)
        source = f.read_bytes()
        results = extract_nodes(tree, lang, source, "function_definition", "__init__")
        assert len(results) == 2
        assert [r["start_line"] for r in results] == [2, 6]
        assert "self.a = 1" in results[0]["text"]
        assert "self.b = 2" in results[1]["text"]


RUST_SOURCE = """\
struct Point {
    x: f64,
    y: f64,
}

fn distance(a: &Point, b: &Point) -> f64 {
    ((a.x - b.x).powi(2) + (a.y - b.y).powi(2)).sqrt()
}
"""

TS_SOURCE = """\
interface Shape {
    area(): number;
}

class Circle implements Shape {
    constructor(private radius: number) {}

    area(): number {
        return Math.PI * this.radius ** 2;
    }
}

function greet(name: string): string {
    return `Hello, ${name}`;
}
"""

JS_SOURCE = """\
class Animal {
    speak() {
        return "...";
    }
}

function add(a, b) {
    return a + b;
}
"""


class TestAdditionalLanguages:
    def test_rust_parse_and_outline(self, tmp_path):
        f = tmp_path / "lib.rs"
        f.write_text(RUST_SOURCE)
        tree, lang = parse_file(f)
        assert lang == "rust"
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert "Point" in names
        assert "distance" in names

    def test_typescript_parse_and_outline(self, tmp_path):
        f = tmp_path / "app.ts"
        f.write_text(TS_SOURCE)
        tree, lang = parse_file(f)
        assert lang == "typescript"
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert "Shape" in names
        assert "Circle" in names
        assert "greet" in names

    def test_tsx_parse(self, tmp_path):
        f = tmp_path / "component.tsx"
        f.write_text(TS_SOURCE)
        tree, lang = parse_file(f)
        assert lang == "tsx"
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert "Shape" in names

    def test_javascript_parse_and_outline(self, tmp_path):
        f = tmp_path / "index.js"
        f.write_text(JS_SOURCE)
        tree, lang = parse_file(f)
        assert lang == "javascript"
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert "Animal" in names
        assert "add" in names

    def test_rust_scope(self, tmp_path):
        f = tmp_path / "lib.rs"
        f.write_text(RUST_SOURCE)
        tree, lang = parse_file(f)
        scopes = get_scope_at_position(tree, lang, 6, 4)
        types = [s["type"] for s in scopes]
        assert "source_file" in types
        assert "function_item" in types

    def test_typescript_scope(self, tmp_path):
        f = tmp_path / "app.ts"
        f.write_text(TS_SOURCE)
        tree, lang = parse_file(f)
        scopes = get_scope_at_position(tree, lang, 8, 8)
        types = [s["type"] for s in scopes]
        assert "program" in types

    def test_javascript_scope(self, tmp_path):
        f = tmp_path / "index.js"
        f.write_text(JS_SOURCE)
        tree, lang = parse_file(f)
        scopes = get_scope_at_position(tree, lang, 7, 4)
        types = [s["type"] for s in scopes]
        assert "program" in types
        assert "function_declaration" in types

    def test_rust_extract(self, tmp_path):
        f = tmp_path / "lib.rs"
        f.write_text(RUST_SOURCE)
        tree, lang = parse_file(f)
        source = f.read_bytes()
        results = extract_nodes(tree, lang, source, "function_item", "distance")
        assert len(results) == 1
        assert "fn distance" in results[0]["text"]

    def test_extract_invalid_node_type_query_fails(self, tmp_path):
        from mcp_servers.lsp.treesitter import InvalidNodeTypeError

        f = tmp_path / "example.py"
        f.write_text(PYTHON_SOURCE)
        tree, lang = parse_file(f)
        source = f.read_bytes()
        with pytest.raises(InvalidNodeTypeError, match="Invalid node type"):
            extract_nodes(tree, lang, source, "nonexistent_node_type_xyz", "foo")

    def test_extract_invalid_node_type_regex(self, tmp_path):
        from mcp_servers.lsp.treesitter import InvalidNodeTypeError

        f = tmp_path / "example.py"
        f.write_text(PYTHON_SOURCE)
        tree, lang = parse_file(f)
        source = f.read_bytes()
        with pytest.raises(InvalidNodeTypeError, match="must be lowercase"):
            extract_nodes(tree, lang, source, "Bad-Node(Type)", "foo")


class TestEdgeCases:
    def test_outline_unsupported_language_raises(self, python_file, mocker):
        from mcp_servers.lsp.treesitter import _OUTLINE_QUERIES

        tree, _ = parse_file(python_file)
        mocker.patch.dict(_OUTLINE_QUERIES, clear=True)
        with pytest.raises(ValueError, match="No outline query"):
            get_outline(tree, "python")

    def test_scope_unsupported_language_raises(self, python_file, mocker):
        from mcp_servers.lsp.treesitter import _SCOPE_NODE_TYPES

        tree, _ = parse_file(python_file)
        mocker.patch.dict(_SCOPE_NODE_TYPES, clear=True)
        with pytest.raises(ValueError, match="No scope info"):
            get_scope_at_position(tree, "python", 0, 0)

    def test_outline_keeps_distinct_same_named_symbols(self, tmp_path):
        f = tmp_path / "dup.py"
        f.write_text("def foo(): pass\ndef foo(): pass\n")
        tree, lang = parse_file(f)
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert names.count("foo") == 2

    def test_outline_skips_empty_captures(self, python_file, mocker):
        """Covers the `not name_nodes or not def_nodes` guard in get_outline."""
        from mcp_servers.lsp import treesitter as ts_mod

        tree, lang = parse_file(python_file)

        mocker.patch.dict(ts_mod._OUTLINE_QUERIES, {"python": "(identifier) @other"})
        symbols = ts_mod.get_outline(tree, "python")
        assert symbols == []

    def test_outline_deduplicates_same_def_node(self, python_file, mocker):
        """Covers the `def_node.id in seen_ids` guard in get_outline."""
        import tree_sitter as ts

        tree, lang = parse_file(python_file)
        orig_matches = ts.QueryCursor.matches

        def patched_matches(self, node):
            results = orig_matches(self, node)
            if results:
                results = results + [results[0]]
            return results

        mocker.patch.object(ts.QueryCursor, "matches", patched_matches)
        symbols = get_outline(tree, lang)
        names = [s["name"] for s in symbols]
        assert names.count("Greeter") == 1

    def test_extract_node_no_captures(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        results = extract_nodes(tree, lang, source, "function_definition", "nonexistent_xyz")
        assert results == []

    def test_extract_node_query_returns_partial_captures(self, python_file, mocker):
        """Covers the `not name_nodes or not def_nodes` guard in extract_nodes."""
        import tree_sitter as ts

        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()

        orig_matches = ts.QueryCursor.matches

        def patched_matches(self, node):
            # Return a match with empty captures to trigger the guard
            return [(0, {"name": [], "def": []})] + orig_matches(self, node)

        mocker.patch.object(ts.QueryCursor, "matches", patched_matches)
        results = extract_nodes(tree, lang, source, "function_definition", "standalone")
        assert len(results) == 1
        assert "def standalone" in results[0]["text"]

    def test_extract_deduplicates_same_def_node(self, python_file, mocker):
        """Covers the `def_node.id in seen_ids` guard in extract_nodes."""
        import tree_sitter as ts

        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        orig_matches = ts.QueryCursor.matches

        def patched_matches(self, node):
            # Emit every match twice so the same def node is seen more than once.
            results = orig_matches(self, node)
            return results + results

        mocker.patch.object(ts.QueryCursor, "matches", patched_matches)
        results = extract_nodes(tree, lang, source, "function_definition", "standalone")
        assert len(results) == 1
        assert "def standalone" in results[0]["text"]


class TestToolFunctions:
    """Test the MCP tool wrappers."""

    @pytest.fixture(autouse=True)
    def _setup_workspace(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        self.python_file = tmp_path / "example.py"
        self.python_file.write_text(PYTHON_SOURCE)
        monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))

    @pytest.mark.asyncio
    async def test_ts_query_tool(self):
        from mcp_servers.lsp.models.schemas import TsQueryArgs
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(
            TsQueryArgs(
                filepath=str(self.python_file),
                query="(function_definition name: (identifier) @name)",
            )
        )
        assert "greet" in result
        assert "standalone" in result

    @pytest.mark.asyncio
    async def test_ts_query_bad_file(self):
        from mcp_servers.lsp.models.schemas import TsQueryArgs
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(
            TsQueryArgs(filepath=str(self.tmp_path / "nope.py"), query="(identifier) @id")
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_query_bad_pattern(self):
        from mcp_servers.lsp.models.schemas import TsQueryArgs
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(
            TsQueryArgs(filepath=str(self.python_file), query="(((invalid_syntax")
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_query_no_matches(self):
        from mcp_servers.lsp.models.schemas import TsQueryArgs
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(
            TsQueryArgs(filepath=str(self.python_file), query="(while_statement) @loop")
        )
        assert result == "No matches found."

    @pytest.mark.asyncio
    async def test_ts_outline_tool(self):
        from mcp_servers.lsp.models.schemas import TsOutlineArgs
        from mcp_servers.lsp.tools.treesitter import ts_outline

        result = await ts_outline(TsOutlineArgs(filepath=str(self.python_file)))
        assert "Greeter" in result
        assert "greet" in result
        assert "standalone" in result

    @pytest.mark.asyncio
    async def test_ts_outline_bad_file(self):
        from mcp_servers.lsp.models.schemas import TsOutlineArgs
        from mcp_servers.lsp.tools.treesitter import ts_outline

        result = await ts_outline(TsOutlineArgs(filepath=str(self.tmp_path / "nope.py")))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_extract_tool(self):
        from mcp_servers.lsp.models.schemas import TsExtractArgs
        from mcp_servers.lsp.tools.treesitter import ts_extract

        result = await ts_extract(
            TsExtractArgs(
                filepath=str(self.python_file), node_type="function_definition", name="standalone"
            )
        )
        assert "def standalone" in result
        assert "return -x" in result

    @pytest.mark.asyncio
    async def test_ts_extract_not_found(self):
        from mcp_servers.lsp.models.schemas import TsExtractArgs
        from mcp_servers.lsp.tools.treesitter import ts_extract

        result = await ts_extract(
            TsExtractArgs(
                filepath=str(self.python_file), node_type="function_definition", name="nope"
            )
        )
        assert "No function_definition named 'nope' found" in result

    @pytest.mark.asyncio
    async def test_ts_extract_ambiguous_shows_all(self):
        from mcp_servers.lsp.models.schemas import TsExtractArgs
        from mcp_servers.lsp.tools.treesitter import ts_extract

        f = self.tmp_path / "dup.py"
        f.write_text(
            "class A:\n"
            "    def __init__(self):\n"
            "        self.a = 1\n"
            "\n"
            "class B:\n"
            "    def __init__(self):\n"
            "        self.b = 2\n"
        )
        result = await ts_extract(
            TsExtractArgs(filepath=str(f), node_type="function_definition", name="__init__")
        )
        assert "2 function_definition nodes named '__init__' found" in result
        assert "self.a = 1" in result
        assert "self.b = 2" in result

    @pytest.mark.asyncio
    async def test_ts_scope_module_end_line(self):
        from mcp_servers.lsp.models.schemas import TsScopeArgs
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        f = self.tmp_path / "trailing.py"
        f.write_text("def a():\n    return 1\ndef b():\n    return 2\n")
        result = await ts_scope_at_position(TsScopeArgs(filepath=str(f), line=3, char=0))
        assert "module  (lines 1-4)" in result

    @pytest.mark.asyncio
    async def test_ts_scope_tool(self):
        from mcp_servers.lsp.models.schemas import TsScopeArgs
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        result = await ts_scope_at_position(
            TsScopeArgs(filepath=str(self.python_file), line=2, char=8)
        )
        assert "module" in result
        assert "class_definition" in result
        assert "Greeter" in result

    @pytest.mark.asyncio
    async def test_ts_scope_bad_line(self):
        from mcp_servers.lsp.models.schemas import TsScopeArgs

        with pytest.raises(ValidationError):
            TsScopeArgs(filepath=str(self.python_file), line=0, char=0)

    @pytest.mark.asyncio
    async def test_ts_scope_bad_file(self):
        from mcp_servers.lsp.models.schemas import TsScopeArgs
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        result = await ts_scope_at_position(
            TsScopeArgs(filepath=str(self.tmp_path / "nope.py"), line=1, char=0)
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_outline_unsupported_ext(self):
        from mcp_servers.lsp.models.schemas import TsOutlineArgs
        from mcp_servers.lsp.tools.treesitter import ts_outline

        f = self.tmp_path / "data.csv"
        f.write_text("a,b,c")
        result = await ts_outline(TsOutlineArgs(filepath=str(f)))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_query_unsupported_ext(self):
        from mcp_servers.lsp.models.schemas import TsQueryArgs
        from mcp_servers.lsp.tools.treesitter import ts_query

        f = self.tmp_path / "data.csv"
        f.write_text("a,b,c")
        result = await ts_query(TsQueryArgs(filepath=str(f), query="(identifier) @id"))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_extract_unsupported_ext(self):
        from mcp_servers.lsp.models.schemas import TsExtractArgs
        from mcp_servers.lsp.tools.treesitter import ts_extract

        f = self.tmp_path / "data.csv"
        f.write_text("a,b,c")
        result = await ts_extract(
            TsExtractArgs(filepath=str(f), node_type="function_definition", name="foo")
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_scope_unsupported_ext(self):
        from mcp_servers.lsp.models.schemas import TsScopeArgs
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        f = self.tmp_path / "data.csv"
        f.write_text("a,b,c")
        result = await ts_scope_at_position(TsScopeArgs(filepath=str(f), line=1, char=0))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_outline_get_outline_raises(self, mocker):
        from mcp_servers.lsp.models.schemas import TsOutlineArgs
        from mcp_servers.lsp.tools.treesitter import ts_outline
        from mcp_servers.lsp.treesitter import _OUTLINE_QUERIES

        mocker.patch.dict(_OUTLINE_QUERIES, clear=True)
        result = await ts_outline(TsOutlineArgs(filepath=str(self.python_file)))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_scope_get_scope_raises(self, mocker):
        from mcp_servers.lsp.models.schemas import TsScopeArgs
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position
        from mcp_servers.lsp.treesitter import _SCOPE_NODE_TYPES

        mocker.patch.dict(_SCOPE_NODE_TYPES, clear=True)
        result = await ts_scope_at_position(
            TsScopeArgs(filepath=str(self.python_file), line=1, char=0)
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_outline_empty_file(self):
        from mcp_servers.lsp.models.schemas import TsOutlineArgs
        from mcp_servers.lsp.tools.treesitter import ts_outline

        f = self.tmp_path / "empty.py"
        f.write_text("")
        result = await ts_outline(TsOutlineArgs(filepath=str(f)))
        assert result == "No symbols found."

    @pytest.mark.asyncio
    async def test_ts_query_long_text_truncation(self):
        from mcp_servers.lsp.models.schemas import TsQueryArgs
        from mcp_servers.lsp.tools.treesitter import ts_query

        f = self.tmp_path / "long.py"
        f.write_text(f"x = '{'a' * 200}'\n")
        result = await ts_query(TsQueryArgs(filepath=str(f), query="(string (string_content) @s)"))
        assert "..." in result

    @pytest.mark.asyncio
    async def test_ts_scope_no_scope_found(self, mocker):
        from mcp_servers.lsp.models.schemas import TsScopeArgs
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position
        from mcp_servers.lsp.treesitter import _SCOPE_NODE_TYPES

        empty_types: dict[str, set[str]] = {"python": set()}
        mocker.patch.dict(_SCOPE_NODE_TYPES, empty_types, clear=True)
        result = await ts_scope_at_position(
            TsScopeArgs(filepath=str(self.python_file), line=1, char=0)
        )
        assert result == "No enclosing scope found."

    @pytest.mark.asyncio
    async def test_ts_extract_bad_file(self):
        from mcp_servers.lsp.models.schemas import TsExtractArgs
        from mcp_servers.lsp.tools.treesitter import ts_extract

        result = await ts_extract(
            TsExtractArgs(
                filepath=str(self.tmp_path / "nope.py"), node_type="function_definition", name="foo"
            )
        )
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_extract_invalid_node_type(self):
        from mcp_servers.lsp.models.schemas import TsExtractArgs
        from mcp_servers.lsp.tools.treesitter import ts_extract

        result = await ts_extract(
            TsExtractArgs(
                filepath=str(self.python_file), node_type="nonexistent_node_xyz", name="foo"
            )
        )
        assert "Error" in result
        assert "Invalid node type" in result
