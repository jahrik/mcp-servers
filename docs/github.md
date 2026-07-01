# github

A GitHub server backed by the **`gh` CLI**. Because it shells out to `gh`, it **reuses your existing `gh auth login` session** — no Personal Access Token, no secret in any config file, no OAuth flow. If `gh` is logged in, the server works.

## Read Tools

- `gh_repo_list`
- `gh_repo_get`
- `gh_pr_list`
- `gh_pr_get`
- `gh_pr_diff`
- `gh_pr_checks`
- `gh_issue_list`
- `gh_issue_get`
- `gh_file_get`
- `gh_search_code`
- `gh_search_prs`
- `gh_search_issues`
- `gh_run_list`
- `gh_run_get`
- `gh_run_failed_logs`
- `gh_review_comments_list`
- `gh_review_threads_get`
- `gh_api_get`
- `gh_graphql_query`

The review-read tools take `bot_only` to keep just the Copilot/bot comments — the actionable ones in a review.

## Write Tools

- `gh_pr_create`
- `gh_pr_edit`
- `gh_pr_comment`
- `gh_pr_merge`
- `gh_issue_create`
- `gh_issue_comment`
- `gh_review_comment_reply`
- `gh_review_thread_resolve`

Every write tool invocation is recorded for accountability in a local SQLite audit log at `~/.mcp/audit.db`.

## Production Hardening

This server includes several features designed to make it robust and safe for AI agent use:
- **Rich Schema Validation**: Uses Pydantic to strictly validate inputs (e.g., repository names, issue numbers) before shelling out to `gh`, blocking malformed inputs.
- **Enhanced Audit Logging**: The SQLite audit log captures not just the command, but also the execution duration, success status, and full stderr for complete observability.
- **Actionable Error Handling**: On failure, the server returns AI-friendly hints and clear context rather than raw Python stack traces, helping agents self-correct.
