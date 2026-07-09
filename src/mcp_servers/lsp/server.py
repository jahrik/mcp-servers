"""MCP server that wraps an external LSP (Language Server Protocol) process.

This server provides tools to query an underlying LSP server (e.g. ty)
for hover information, diagnostics, and more.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

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

mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(tools.lsp_hover)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_definition
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_references
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_document_symbols
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_workspace_symbols
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_diagnostics
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_type_definition
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_implementation
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_document_highlight
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_call_hierarchy
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))(tools.lsp_rename)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.lsp_code_actions
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))(
    tools.lsp_execute_code_action
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))(tools.lsp_format)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(tools.ts_query)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(tools.ts_outline)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(tools.ts_extract)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))(
    tools.ts_scope_at_position
)


def main() -> None:
    """Run the lsp MCP server."""
    level = logging.getLevelNamesMapping().get(
        os.getenv("MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING
    )
    logging.basicConfig(stream=sys.stderr, level=level)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
