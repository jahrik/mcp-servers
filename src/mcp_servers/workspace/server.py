"""A small, read-only workspace MCP server.

Reports on the state of the local git workspace — dirty trees, diverged or
untracked branches, stale branches — across every repo under one root
directory (default ``~/github``, override with ``MCP_WORKSPACE_ROOT``).

It never mutates a working copy: every git invocation is a fixed-argv,
read-only command. Cleanup stays a human/agent decision made with the full
report in hand.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("workspace")

# Register all tools
mcp.tool()(tools.ws_status)
mcp.tool()(tools.ws_repo)
mcp.tool()(tools.ws_branches)
mcp.tool()(tools.ws_log)


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    level = logging.getLevelNamesMapping().get(
        os.getenv("MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING
    )
    logging.basicConfig(stream=sys.stderr, level=level)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
