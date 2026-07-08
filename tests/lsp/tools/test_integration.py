from __future__ import annotations

import asyncio
import shutil

import pytest
from mcp.server.fastmcp import Context

from mcp_servers.lsp import utils
from mcp_servers.lsp.models.schemas import (
    DocumentSymbolsArgs,
    PositionArgs,
    WorkspaceSymbolsArgs,
)
from mcp_servers.lsp.tools import (
    lsp_definition,
    lsp_document_symbols,
    lsp_hover,
    lsp_references,
    lsp_workspace_symbols,
)

ty = shutil.which("ty")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(ty is None, reason="ty language server not installed"),
]


@pytest.fixture(autouse=True)
async def lsp_client_lifespan(tmp_path, monkeypatch):
    # Set workspace root
    monkeypatch.setattr("mcp_servers.lsp.utils.WORKSPACE_ROOT", str(tmp_path))
    # Initialize real lsp_client
    await utils.lsp_client.initialize(tmp_path.as_uri())
    await utils.lsp_client.start()
    yield
    await utils.lsp_client.stop()


@pytest.mark.asyncio
async def test_ty_integration(tmp_path):
    # Create a small python fixture
    code = """\
class Calculator:
    def add(self, a: int, b: int) -> int:
        \"\"\"Add two numbers.\"\"\"
        return a + b

def run():
    calc = Calculator()
    calc.add(1, 2)
"""
    fixture_file = tmp_path / "calc.py"
    fixture_file.write_text(code, encoding="utf-8")

    ctx = Context()

    # Wait a bit for the language server to initialize and recognize the file structure
    await asyncio.sleep(2.0)

    # 1. Drive lsp_document_symbols
    # This should return a list of symbols: Calculator, Calculator.add, run
    args_sym = DocumentSymbolsArgs(filepath=str(fixture_file))
    symbols_res = await lsp_document_symbols(args_sym, ctx)
    assert "Calculator" in symbols_res
    assert "add" in symbols_res
    assert "run" in symbols_res

    # 2. Drive lsp_hover on the `add` method documentation (line 8, char 9)
    args_hover = PositionArgs(filepath=str(fixture_file), line=8, char=9)
    hover_res = await lsp_hover(args_hover, ctx)
    assert "Add two numbers" in hover_res

    # 3. Drive lsp_definition from the `Calculator()` call on line 7 (char 12)
    # This should jump to the class Calculator definition on line 1, char 6
    args_def = PositionArgs(filepath=str(fixture_file), line=7, char=12)
    def_res = await lsp_definition(args_def, ctx)
    assert "calc.py:1:6" in def_res

    # 4. Drive lsp_references on `Calculator` on line 1, char 6
    # This should return references to Calculator on line 1 and line 7
    args_refs = PositionArgs(filepath=str(fixture_file), line=1, char=6)
    refs_res = await lsp_references(args_refs, ctx)
    assert "calc.py:1:6" in refs_res
    assert "calc.py:7:11" in refs_res

    # 5. Drive lsp_workspace_symbols. WORKSPACE_ROOT is monkeypatched to tmp_path,
    # so this resolves either via the LSP or the tree-sitter fallback (for backends
    # that don't index the workspace) — either way the fixture's symbols must appear.
    args_ws = WorkspaceSymbolsArgs(query="Calculator")
    ws_res = await lsp_workspace_symbols(args_ws, ctx)
    assert "Calculator" in ws_res
