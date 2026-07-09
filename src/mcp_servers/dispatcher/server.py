"""A dispatcher MCP server for delegating jobs to subagents.

Manages job state and peer-to-peer messages in an SQLite database.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import tools

mcp = FastMCP("dispatcher")

# Register tools
mcp.tool()(tools.submit_job)
mcp.tool()(tools.claim_job)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.get_job_status)
mcp.tool()(tools.update_job_status)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.list_jobs)
mcp.tool(annotations=ToolAnnotations(destructiveHint=True))(tools.cleanup_jobs)
mcp.tool()(tools.send_message)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.get_messages)
mcp.tool()(tools.heartbeat_job)
mcp.tool()(tools.requeue_stalled_jobs)


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    level = logging.getLevelNamesMapping().get(
        os.getenv("MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING
    )
    logging.basicConfig(stream=sys.stderr, level=level)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
