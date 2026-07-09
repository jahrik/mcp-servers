from __future__ import annotations

import pytest

from mcp_servers.data.server import mcp as data_mcp
from mcp_servers.dispatcher.server import mcp as dispatcher_mcp
from mcp_servers.github.server import mcp as github_mcp
from mcp_servers.lsp.server import mcp as lsp_mcp
from mcp_servers.memory.server import mcp as memory_mcp
from mcp_servers.workspace.server import mcp as workspace_mcp

EXPECTED_MAPS = {
    "data": {
        "duckdb_close_database": {"destructiveHint": True, "readOnlyHint": False},
        "duckdb_describe": {"destructiveHint": False, "readOnlyHint": True},
        "duckdb_list_tables": {"destructiveHint": False, "readOnlyHint": True},
        "duckdb_query": {"destructiveHint": True, "readOnlyHint": False},
    },
    "dispatcher": {
        "claim_job": {"destructiveHint": False, "readOnlyHint": False},
        "cleanup_jobs": {"destructiveHint": True, "readOnlyHint": False},
        "get_job_status": {"destructiveHint": False, "readOnlyHint": True},
        "get_messages": {"destructiveHint": False, "readOnlyHint": True},
        "heartbeat_job": {"destructiveHint": False, "idempotentHint": True, "readOnlyHint": False},
        "list_jobs": {"destructiveHint": False, "readOnlyHint": True},
        "requeue_stalled_jobs": {"destructiveHint": False, "readOnlyHint": False},
        "send_message": {"destructiveHint": False, "readOnlyHint": False},
        "submit_job": {"destructiveHint": False, "readOnlyHint": False},
        "update_job_status": {
            "destructiveHint": False,
            "idempotentHint": True,
            "readOnlyHint": False,
        },
    },
    "github": {
        "gh_api_get": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_api_graphql": {"destructiveHint": True, "openWorldHint": True, "readOnlyHint": False},
        "gh_file_get": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_issue_comment": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": False,
        },
        "gh_issue_create": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": False},
        "gh_issue_edit": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": False},
        "gh_issue_get": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_issue_list": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_pr_checks": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_pr_comment": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": False},
        "gh_pr_create": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": False},
        "gh_pr_diff": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_pr_edit": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": False},
        "gh_pr_get": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_pr_list": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_pr_merge": {"destructiveHint": True, "openWorldHint": True, "readOnlyHint": False},
        "gh_pr_request_reviewers": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": False,
        },
        "gh_repo_get": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_repo_list": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_review_comment_reply": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": False,
        },
        "gh_review_comments_list": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": True,
        },
        "gh_review_thread_resolve": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": False,
        },
        "gh_review_threads_get": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": True,
        },
        "gh_run_failed_logs": {
            "destructiveHint": False,
            "openWorldHint": True,
            "readOnlyHint": True,
        },
        "gh_run_get": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_run_list": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_run_rerun": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": False},
        "gh_search_code": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_search_issues": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
        "gh_search_prs": {"destructiveHint": False, "openWorldHint": True, "readOnlyHint": True},
    },
    "lsp": {
        "lsp_call_hierarchy": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_code_actions": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_definition": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_diagnostics": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_document_highlight": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_document_symbols": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_execute_code_action": {"destructiveHint": True, "readOnlyHint": False},
        "lsp_format": {"destructiveHint": True, "readOnlyHint": False},
        "lsp_hover": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_implementation": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_references": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_rename": {"destructiveHint": True, "readOnlyHint": False},
        "lsp_type_definition": {"destructiveHint": False, "readOnlyHint": True},
        "lsp_workspace_symbols": {"destructiveHint": False, "readOnlyHint": True},
        "ts_extract": {"destructiveHint": False, "readOnlyHint": True},
        "ts_outline": {"destructiveHint": False, "readOnlyHint": True},
        "ts_query": {"destructiveHint": False, "readOnlyHint": True},
        "ts_scope_at_position": {"destructiveHint": False, "readOnlyHint": True},
    },
    "memory": {
        "forget": {"destructiveHint": True, "readOnlyHint": False},
        "list_memories": {"destructiveHint": False, "readOnlyHint": True},
        "recall": {"destructiveHint": False, "readOnlyHint": True},
        "remember": {"destructiveHint": False, "readOnlyHint": False},
    },
    "workspace": {
        "ws_branches": {"destructiveHint": False, "idempotentHint": True, "readOnlyHint": True},
        "ws_log": {"destructiveHint": False, "idempotentHint": True, "readOnlyHint": True},
        "ws_repo": {"destructiveHint": False, "idempotentHint": True, "readOnlyHint": True},
        "ws_status": {"destructiveHint": False, "idempotentHint": True, "readOnlyHint": True},
    },
}


@pytest.mark.parametrize(
    ("mcp_instance", "expected_map"),
    [
        (data_mcp, EXPECTED_MAPS["data"]),
        (dispatcher_mcp, EXPECTED_MAPS["dispatcher"]),
        (github_mcp, EXPECTED_MAPS["github"]),
        (lsp_mcp, EXPECTED_MAPS["lsp"]),
        (memory_mcp, EXPECTED_MAPS["memory"]),
        (workspace_mcp, EXPECTED_MAPS["workspace"]),
    ],
    ids=["data", "dispatcher", "github", "lsp", "memory", "workspace"],
)
def test_tool_annotations(mcp_instance, expected_map):
    tools = mcp_instance._tool_manager.list_tools()
    tools_by_name = {t.name: t for t in tools}

    # Assert every tool in the expected map is registered and has correct annotations
    for t_name, expected_attrs in expected_map.items():
        assert t_name in tools_by_name, f"Tool {t_name} not found in server"
        t = tools_by_name[t_name]

        assert t.annotations is not None, f"Tool {t_name} is completely missing annotations"

        for attr, expected_val in expected_attrs.items():
            actual_val = getattr(t.annotations, attr)
            assert actual_val == expected_val, (
                f"Tool {t_name} annotation {attr} should be {expected_val}, got {actual_val}"
            )

    # Assert no extra tools exist in the server that aren't mapped
    assert set(tools_by_name.keys()) == set(expected_map.keys()), (
        "Mismatch in tools registered vs mapped"
    )
