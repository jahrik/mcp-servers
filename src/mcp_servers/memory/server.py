"""mcp-memory Server — a persistent long-term memory server using DuckDB.

Allows agents to store, recall, list, and delete memories across sessions.
Includes support for syncing past conversation data and artifacts.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import tools

# Create a FastMCP instance for the memory server
mcp = FastMCP("memory")

# Register tools
mcp.tool()(tools.remember)
mcp.tool()(tools.recall)
mcp.tool()(tools.forget)
mcp.tool()(tools.list_memories)
mcp.tool()(tools.sync_existing_data)


def main() -> None:
    """Console-script entry point."""
    level_name = os.getenv("MCP_LOG_LEVEL", "WARNING").upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.WARNING)
    logging.basicConfig(stream=sys.stderr, level=level)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
