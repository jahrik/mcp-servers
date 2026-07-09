"""mcp-memory Server — a persistent long-term memory server using DuckDB.

Allows agents to store, recall, list, and delete memories across sessions.
Includes support for syncing past conversation data and artifacts.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import tools

# Create a FastMCP instance for the memory server
mcp = FastMCP("memory")

# Register tools
mcp.tool()(tools.remember)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.recall)
mcp.tool(annotations=ToolAnnotations(destructiveHint=True))(tools.forget)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.list_memories)


def main() -> None:
    """Console-script entry point."""
    level_name = os.getenv("MCP_LOG_LEVEL", "WARNING").upper()
    level = logging.getLevelNamesMapping().get(level_name, logging.WARNING)
    logging.basicConfig(stream=sys.stderr, level=level)

    # Initialize the database schema once, sequentially, before serving requests.
    # This avoids catalog write-write conflicts from concurrent lazy init on a
    # cold-start database.
    from .tools.db import get_db_conn

    with get_db_conn(read_only=False):
        pass

    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
