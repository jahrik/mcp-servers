"""data MCP Server — local data analysis without burning context.

Lets an agent run SQL over large local files (CSV/JSON/JSONL/Parquet) in place
and keep scratch tables alive across tool calls, pulling only answer rows into
the context window. DuckDB is the engine, so tools keep the duckdb_* prefix —
the name tells the agent which SQL dialect and file-query idioms apply.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import tools

mcp = FastMCP("data")

# Register tools
mcp.tool()(tools.duckdb_query)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.duckdb_describe)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))(tools.duckdb_list_tables)
mcp.tool()(tools.duckdb_close_database)


def main() -> None:
    """Console-script entry point."""
    level = logging.getLevelNamesMapping().get(
        os.getenv("MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING
    )
    logging.basicConfig(stream=sys.stderr, level=level)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
