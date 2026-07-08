from pathlib import Path
from unittest.mock import patch

import pytest

from mcp_servers.lsp.treesitter import (
    detect_language,
    extract_node,
    get_outline,
    get_scope_at_position,
    parse_file,
    run_query,
)


def _patch_root(root: Path):
    return patch("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(root))


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

    def test_standalone_function(self, python_file):
        tree, lang = parse_file(python_file)
        scopes = get_scope_at_position(tree, lang, 5, 4)
        names = [s["name"] for s in scopes if s["name"]]
        assert "standalone" in names
        assert "Greeter" not in names


class TestExtractNode:
    def test_extract_function(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        result = extract_node(tree, lang, source, "function_definition", "standalone")
        assert result is not None
        assert "def standalone" in result["text"]
        assert "return -x" in result["text"]
        assert result["start_line"] == 5
        assert result["end_line"] == 8

    def test_extract_class(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        result = extract_node(tree, lang, source, "class_definition", "Greeter")
        assert result is not None
        assert "class Greeter" in result["text"]
        assert "def greet" in result["text"]

    def test_extract_not_found(self, python_file):
        tree, lang = parse_file(python_file)
        source = python_file.read_bytes()
        result = extract_node(tree, lang, source, "function_definition", "nonexistent")
        assert result is None


class TestToolFunctions:
    """Test the MCP tool wrappers."""

    @pytest.fixture(autouse=True)
    def _setup_workspace(self, tmp_path):
        self.tmp_path = tmp_path
        self.python_file = tmp_path / "example.py"
        self.python_file.write_text(PYTHON_SOURCE)
        self._patcher = _patch_root(tmp_path)
        self._patcher.start()

    @pytest.fixture(autouse=True)
    def _teardown(self):
        yield
        self._patcher.stop()

    @pytest.mark.asyncio
    async def test_ts_query_tool(self):
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(
            str(self.python_file), "(function_definition name: (identifier) @name)"
        )
        assert "greet" in result
        assert "standalone" in result

    @pytest.mark.asyncio
    async def test_ts_query_bad_file(self):
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(str(self.tmp_path / "nope.py"), "(identifier) @id")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_query_bad_pattern(self):
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(str(self.python_file), "(((invalid_syntax")
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_query_no_matches(self):
        from mcp_servers.lsp.tools.treesitter import ts_query

        result = await ts_query(str(self.python_file), "(while_statement) @loop")
        assert result == "No matches found."

    @pytest.mark.asyncio
    async def test_ts_outline_tool(self):
        from mcp_servers.lsp.tools.treesitter import ts_outline

        result = await ts_outline(str(self.python_file))
        assert "Greeter" in result
        assert "greet" in result
        assert "standalone" in result

    @pytest.mark.asyncio
    async def test_ts_outline_bad_file(self):
        from mcp_servers.lsp.tools.treesitter import ts_outline

        result = await ts_outline(str(self.tmp_path / "nope.py"))
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_extract_tool(self):
        from mcp_servers.lsp.tools.treesitter import ts_extract

        result = await ts_extract(str(self.python_file), "function_definition", "standalone")
        assert "def standalone" in result
        assert "return -x" in result

    @pytest.mark.asyncio
    async def test_ts_extract_not_found(self):
        from mcp_servers.lsp.tools.treesitter import ts_extract

        result = await ts_extract(str(self.python_file), "function_definition", "nope")
        assert "No function_definition named 'nope' found" in result

    @pytest.mark.asyncio
    async def test_ts_scope_tool(self):
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        result = await ts_scope_at_position(str(self.python_file), 2, 8)
        assert "module" in result
        assert "class_definition" in result
        assert "Greeter" in result

    @pytest.mark.asyncio
    async def test_ts_scope_bad_line(self):
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        result = await ts_scope_at_position(str(self.python_file), 0, 0)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_scope_bad_file(self):
        from mcp_servers.lsp.tools.treesitter import ts_scope_at_position

        result = await ts_scope_at_position(str(self.tmp_path / "nope.py"), 1, 0)
        assert "Error" in result

    @pytest.mark.asyncio
    async def test_ts_outline_unsupported_ext(self):
        from mcp_servers.lsp.tools.treesitter import ts_outline

        f = self.tmp_path / "data.csv"
        f.write_text("a,b,c")
        result = await ts_outline(str(f))
        assert "Error" in result
