"""DuckDB MCP Server.

Provides SQL query execution, schema description, and table discovery.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("duckdb")

# Register tools
mcp.tool()(tools.duckdb_query)
mcp.tool()(tools.duckdb_describe)
mcp.tool()(tools.duckdb_list_tables)
mcp.tool()(tools.duckdb_close_database)


def main() -> None:
    """Console-script entry point."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
