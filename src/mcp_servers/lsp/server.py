"""MCP server that wraps an external LSP (Language Server Protocol) process.

This server provides tools to query an underlying LSP server (e.g. pyright)
for hover information, diagnostics, and more.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import tools, utils


@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[dict]:
    try:
        # Start and initialize the LSP server router
        await utils.lsp_client.start()

        # Send initialize handshake
        uri = Path(utils.WORKSPACE_ROOT).resolve().as_uri()
        await utils.lsp_client.initialize(uri)

        yield {}
    finally:
        # Shutdown gracefully
        await utils.lsp_client.stop()


mcp = FastMCP("lsp", lifespan=server_lifespan)

mcp.tool()(tools.lsp_hover)
mcp.tool()(tools.lsp_definition)
mcp.tool()(tools.lsp_references)
mcp.tool()(tools.lsp_document_symbols)
mcp.tool()(tools.lsp_workspace_symbols)
mcp.tool()(tools.lsp_diagnostics)
mcp.tool()(tools.lsp_type_definition)
mcp.tool()(tools.lsp_implementation)
mcp.tool()(tools.lsp_document_highlight)
mcp.tool()(tools.lsp_call_hierarchy)
mcp.tool()(tools.lsp_rename)
mcp.tool()(tools.lsp_code_actions)
mcp.tool()(tools.lsp_execute_code_action)


def main() -> None:
    """Run the lsp MCP server."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
