"""A small, curated GitHub MCP server.

Exposes the handful of operations an agent actually reaches for during code
work — reads plus a narrow set of writes — rather than the full GitHub API
surface. It operates as a pure-Python async HTTP server, authenticating via
a GitHub App using dynamically generated Installation Access Tokens.

Writes are added deliberately, one tool at a time, and are audit-logged to a local
SQLite database. Write operations are disabled by default and must be explicitly
enabled by setting `MCP_GITHUB_ALLOW_WRITE=1`.
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import tools

mcp = FastMCP("github")

# Register all tools
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_repo_list
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_repo_get
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_pr_list
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_pr_get
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_pr_diff
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_pr_checks
)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_pr_create)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_pr_edit)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_pr_comment)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))(
    tools.gh_pr_merge
)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_pr_request_reviewers)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_issue_list
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_issue_get
)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_issue_create)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_issue_comment)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_issue_edit)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_milestone_create)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_milestone_list
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_file_get
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_search_code
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_search_prs
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_search_issues
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_run_list
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_run_get
)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_run_rerun)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_run_failed_logs
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_review_comments_list
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_review_threads_get
)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_review_comment_reply)
mcp.tool(
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
)(tools.gh_review_thread_resolve)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True))(
    tools.gh_api_get
)
mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True))(
    tools.gh_api_graphql
)


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    level = logging.getLevelNamesMapping().get(
        os.getenv("MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING
    )
    logging.basicConfig(stream=sys.stderr, level=level)
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
