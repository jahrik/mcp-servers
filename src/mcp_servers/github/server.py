"""A small, curated GitHub MCP server.

Exposes the handful of operations an agent actually reaches for during code
work — reads plus a narrow set of writes — rather than the full GitHub API
surface. Every tool shells out to `gh`, so it authenticates with your existing
`gh auth login` session and needs no token.

Writes are added deliberately, one tool at a time (currently the PR review-thread
loop: reply, resolve). The server never merges a PR or pushes to a default
branch — those stay out by design.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import tools

mcp = FastMCP("github")

# Register all tools
mcp.tool()(tools.gh_repo_list)
mcp.tool()(tools.gh_repo_get)
mcp.tool()(tools.gh_pr_list)
mcp.tool()(tools.gh_pr_get)
mcp.tool()(tools.gh_pr_diff)
mcp.tool()(tools.gh_pr_checks)
mcp.tool()(tools.gh_pr_create)
mcp.tool()(tools.gh_pr_comment)
mcp.tool()(tools.gh_pr_merge)
mcp.tool()(tools.gh_issue_list)
mcp.tool()(tools.gh_issue_get)
mcp.tool()(tools.gh_issue_create)
mcp.tool()(tools.gh_issue_comment)
mcp.tool()(tools.gh_file_get)
mcp.tool()(tools.gh_search_code)
mcp.tool()(tools.gh_search_prs)
mcp.tool()(tools.gh_search_issues)
mcp.tool()(tools.gh_run_list)
mcp.tool()(tools.gh_run_get)
mcp.tool()(tools.gh_run_failed_logs)
mcp.tool()(tools.gh_review_comments_list)
mcp.tool()(tools.gh_review_threads_get)
mcp.tool()(tools.gh_review_comment_reply)
mcp.tool()(tools.gh_review_thread_resolve)
mcp.tool()(tools.gh_api_get)
mcp.tool()(tools.gh_graphql_query)


def main() -> None:
    """Console-script entry point — run the server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
