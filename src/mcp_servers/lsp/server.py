"""MCP server that wraps an external LSP (Language Server Protocol) process.

This server provides tools to query an underlying LSP server (e.g. pyright)
for hover information, diagnostics, and more.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from mcp_servers.lsp.client import LSPClient

# Use pyright by default, allow override via env
LSP_COMMAND = shlex.split(os.environ.get("MCP_LSP_COMMAND", "pyright-langserver --stdio"))
WORKSPACE_ROOT = os.environ.get("MCP_LSP_ROOT", os.getcwd())
if WORKSPACE_ROOT.startswith("~"):  # pragma: no cover
    WORKSPACE_ROOT = str(Path(WORKSPACE_ROOT).expanduser())

# Create a global client instance
lsp_client = LSPClient(LSP_COMMAND)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    try:
        # Start and initialize the LSP server
        await lsp_client.start()

        # Send initialize handshake
        uri = Path(WORKSPACE_ROOT).resolve().as_uri()
        await lsp_client.initialize(uri)

        yield {}
    finally:
        # Shutdown gracefully
        await lsp_client.stop()


mcp = FastMCP("lsp", lifespan=server_lifespan)


def _prepare_file(filepath: str) -> Path | str:
    """Validate and resolve filepath. Returns Path on success, error string on failure."""
    p = Path(filepath)
    filepath_obj = (Path(WORKSPACE_ROOT) / p).resolve() if not p.is_absolute() else p.resolve()
    root_obj = Path(WORKSPACE_ROOT).resolve()
    try:
        filepath_obj.relative_to(root_obj)
    except ValueError:
        return f"Error: Filepath must be within the workspace root {WORKSPACE_ROOT}"
    if not filepath_obj.exists():
        return f"Error: File not found: {filepath_obj}"
    return filepath_obj


async def _sync_file_with_lsp(filepath_obj: Path) -> str:
    """Sync file to LSP and return URI."""
    uri = filepath_obj.as_uri()
    filepath = str(filepath_obj)
    language_id = "python"
    if filepath.endswith(".go"):
        language_id = "go"
    elif filepath.endswith(".rs"):
        language_id = "rust"
    elif filepath.endswith((".ts", ".tsx")):
        language_id = "typescript"
    elif filepath.endswith((".js", ".jsx")):
        language_id = "javascript"

    with open(filepath_obj, encoding="utf-8") as f:
        content = f.read()
    await lsp_client.sync_file(uri, language_id, content)
    return uri


@mcp.tool()
async def lsp_hover(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the type signature and docstring for the symbol at the given position.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
    """
    filepath_obj = _prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    if line < 1 or char < 0:
        return "Error: line must be >= 1 and char must be >= 0"

    try:
        uri = await _sync_file_with_lsp(filepath_obj)

        # Send hover request (LSP uses 0-indexed lines)
        params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": char}}
        response = await lsp_client.send_request("textDocument/hover", params)
        if not response:
            return "No hover information found at this position."

        contents = response.get("contents", "")
        if isinstance(contents, dict):
            return contents.get("value", str(contents))
        elif isinstance(contents, list):
            return "\n\n".join(
                [c.get("value", str(c)) if isinstance(c, dict) else str(c) for c in contents]
            )
        else:
            return str(contents)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


@mcp.tool()
async def lsp_definition(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the definition location for the symbol at the given position.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
    """
    filepath_obj = _prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    if line < 1 or char < 0:
        return "Error: line must be >= 1 and char must be >= 0"

    try:
        uri = await _sync_file_with_lsp(filepath_obj)
        params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": char}}
        response = await lsp_client.send_request("textDocument/definition", params)
        if not response:
            return "No definition found at this position."

        # Format response (could be list of locations or single location)
        import json

        return json.dumps(response, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


@mcp.tool()
async def lsp_references(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get all reference locations for the symbol at the given position.

    Args:
        filepath: Absolute or workspace-relative path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
    """
    filepath_obj = _prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    if line < 1 or char < 0:
        return "Error: line must be >= 1 and char must be >= 0"

    try:
        uri = await _sync_file_with_lsp(filepath_obj)
        params = {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": char},
            "context": {"includeDeclaration": True},
        }
        response = await lsp_client.send_request("textDocument/references", params)
        if not response:
            return "No references found at this position."

        import json

        return json.dumps(response, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


@mcp.tool()
async def lsp_document_symbols(filepath: str, ctx: Context) -> str:
    """Get all symbols (classes, functions, methods, etc.) defined in the given file.

    Args:
        filepath: Absolute or workspace-relative path to the file.
    """
    filepath_obj = _prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri = await _sync_file_with_lsp(filepath_obj)
        params = {"textDocument": {"uri": uri}}
        response = await lsp_client.send_request("textDocument/documentSymbol", params)
        if not response:
            return "No symbols found in this document."

        import json

        return json.dumps(response, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


@mcp.tool()
async def lsp_workspace_symbols(query: str, ctx: Context) -> str:
    """Search for a symbol across the entire workspace/project.

    Args:
        query: The symbol name or partial name to search for.
    """
    try:
        params = {"query": query}
        response = await lsp_client.send_request("workspace/symbol", params)
        if not response:
            return f"No workspace symbols found matching query '{query}'."

        import json

        return json.dumps(response, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP: {e}"


@mcp.tool()
async def lsp_diagnostics(filepath: str, ctx: Context) -> str:
    """Get the syntax and type-checking diagnostics for the given file.

    Args:
        filepath: Absolute or workspace-relative path to the file.
    """
    filepath_obj = _prepare_file(filepath)
    if isinstance(filepath_obj, str):
        return filepath_obj

    try:
        uri = await _sync_file_with_lsp(filepath_obj)
        # We need to give the LSP a moment to process and publish diagnostics.
        # Poll briefly, up to 0.5s.
        diagnostics = []
        for _ in range(5):
            diagnostics = lsp_client.get_diagnostics(uri)
            if diagnostics:
                break
            await asyncio.sleep(0.1)

        if not diagnostics:
            return "No diagnostics found for this file (it may be error-free, or the LSP hasn't finished analyzing it yet)."

        import json

        return json.dumps(diagnostics, indent=2)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        return f"Error querying LSP diagnostics: {e}"


def main() -> None:
    """Run the lsp MCP server."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
