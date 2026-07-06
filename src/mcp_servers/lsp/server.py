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

# Create a global client instance
lsp_client = LSPClient(LSP_COMMAND)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    # Start and initialize the LSP server
    await lsp_client.start()

    # Send initialize handshake
    uri = Path(WORKSPACE_ROOT).resolve().as_uri()
    await lsp_client.initialize(uri)

    yield {}

    # Shutdown gracefully
    await lsp_client.stop()


mcp = FastMCP("lsp", lifespan=server_lifespan)


@mcp.tool()
async def lsp_hover(filepath: str, line: int, char: int, ctx: Context) -> str:
    """Get the type signature and docstring for the symbol at the given position.

    Args:
        filepath: Absolute path to the file.
        line: 1-indexed line number.
        char: 0-indexed character position.
    """
    filepath_obj = Path(filepath).resolve()
    root_obj = Path(WORKSPACE_ROOT).resolve()
    try:
        filepath_obj.relative_to(root_obj)
    except ValueError:
        return f"Error: Filepath must be within the workspace root {WORKSPACE_ROOT}"

    if not filepath_obj.exists():
        return f"Error: File not found: {filepath}"

    if line < 1:
        return "Error querying LSP: line must be 1 or greater (1-indexed)."

    uri = filepath_obj.as_uri()

    # Send didOpen/didChange to synchronize VFS
    language_id = "python"
    if filepath.endswith(".go"):
        language_id = "go"
    elif filepath.endswith(".rs"):
        language_id = "rust"

    try:
        with open(filepath_obj, encoding="utf-8") as f:
            content = f.read()
        await lsp_client.sync_file(uri, language_id, content)

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


def main() -> None:
    """Run the lsp MCP server."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
