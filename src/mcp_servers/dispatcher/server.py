"""A dispatcher MCP server for delegating jobs to subagents.

Manages job state in an SQLite database and asynchronously spawns subagents to handle them.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("dispatcher")

# Register tools
mcp.tool()(tools.submit_job)
mcp.tool()(tools.get_job_status)
mcp.tool()(tools.update_job_status)
mcp.tool()(tools.list_jobs)


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
