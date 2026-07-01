This PR addresses ALL open issues in the `mcp-servers` repository, consolidating them into a single rollout, and heavily hardens the codebase for production use.

### Fixes #1: Actions/CI read tools
- Added `gh_run_list` to view workflow runs (with branch/workflow filters).
- Added `gh_run_get` and `gh_run_failed_logs` for deep dives into specific failures.
- Enforced `--json` output and type coercion for reliability.

### Fixes #2: PR checks/status tool
- Added `gh_pr_checks` tool to evaluate PR status checks.

### Fixes #3: Cross-repo search
- Added `gh_pr_search` and `gh_issue_search` tools for finding items across repos.

### Fixes #4: Repo metadata tools
- Added `gh_repo_list` to retrieve repositories for a given owner.
- Added `gh_repo_get` to fetch metadata for a specific repository.

### Fixes #5: PR lifecycle write tools
- Added `gh_pr_create`, `gh_pr_comment`, and `gh_pr_merge` for end-to-end PR workflows.

### Fixes #6: Issue write tools
- Added `gh_issue_create` and `gh_issue_comment`.

### Fixes #8: API Passthrough
- Added `gh_api_get` and `gh_api_graphql` with `jq` filtering.

### Fixes #11: SQLite Audit Log
- Added a `~/.mcp/audit.db` SQLite audit log for all mutating actions (write tools).
- **Production Update**: Enhanced to track execution duration (`duration_ms`), success status, and raw `stderr` output on failures.

### Fixes #12: Discovery & Documentation
- Standardized ALL tools to the `gh_<command>_<action>` naming convention.
- Updated `AGENTS.md` and added `skills/mcp-github/SKILL.md` to ensure AI agents prefer the MCP server over raw CLI commands.

### Fixes #13: Response Caching
- Added in-memory LRU caching for slow-changing read tools (`gh_repo_list`, `gh_repo_get`) to improve latency.

### Production Hardening (MCP & Python Best Practices)
- **Rich Schema Discovery**: Upgraded all tool arguments to use strict **Pydantic V2 `BaseModel`s**, enriching the JSON schema with deep descriptions and regex input hardening (e.g. strict `owner/name` format checks).
- **Actionable Error Handling**: Overhauled the `run_gh` error wrapper to translate raw CLI stack traces into structured, actionable hints for AI agents.
- **Strict Linting & Typing**: Fully typed the codebase, verified with a strict `ty check`. Enabled `ruff` strict rules (`UP`, `I`, `SIM`, `PT`).
- **CI/CD Enforcement**: Upgraded the GitHub Actions workflow to strictly gate merges on 100% `pytest` coverage, `ruff check`, and `ty check`.

All tools have been fully tested using `pytest-mock` with 100% test coverage and follow the `AGENTS.md` guidelines for using argv lists and avoiding shell execution.
