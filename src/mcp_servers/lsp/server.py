from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.fastmcp import Context, FastMCP

from mcp_servers.lsp.client import LSPClient

# Use pyright by default, allow override via env
LSP_COMMAND = os.environ.get("MCP_LSP_COMMAND", "pyright-langserver --stdio").split()
WORKSPACE_ROOT = os.environ.get("MCP_LSP_ROOT", os.getcwd())

# Create a global client instance
lsp_client = LSPClient(LSP_COMMAND)


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    # Start and initialize the LSP server
    await lsp_client.start()

    # Send initialize handshake
    uri = f"file://{WORKSPACE_ROOT}"
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
    if not os.path.isabs(filepath):
        return f"Error: Filepath must be absolute: {filepath}"

    if not os.path.exists(filepath):
        return f"Error: File not found: {filepath}"

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    uri = f"file://{filepath}"

    # Send didOpen to synchronize VFS
    language_id = "python"
    if filepath.endswith(".go"):
        language_id = "go"
    elif filepath.endswith(".rs"):
        language_id = "rust"

    await lsp_client.open_file(uri, language_id, content)

    # Send hover request (LSP uses 0-indexed lines)
    params = {"textDocument": {"uri": uri}, "position": {"line": line - 1, "character": char}}

    try:
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
    except Exception as e:
        return f"Error querying LSP: {e}"


def main() -> None:
    """Run the lsp MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
