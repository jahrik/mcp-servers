# github

GitHub access over REST and GraphQL (via `httpx`), authenticated as a **GitHub App** using
dynamically generated Installation Access Tokens so agent actions are attributed to a dedicated
bot identity (`app-name[bot]`).

Installed as `mcp-github`; registered as `github`.

## Setup: create and install the GitHub App

You need one GitHub App per bot identity you want agent actions attributed to. Do this once;
reuse the same App (and its credentials) across every repo/machine that should act as that bot.

### 1. Create the App

- Personal account: **Settings → Developer settings → GitHub Apps → New GitHub App**
  (`https://github.com/settings/apps/new`)
- Organization: **Org → Settings → Developer settings → GitHub Apps → New GitHub App**
  (`https://github.com/organizations/<org>/settings/apps/new`)

Fill in:
- **GitHub App name** — this becomes the bot identity, e.g. `my-agent-bot` shows up as
  `my-agent-bot[bot]` on commits/comments/merges.
- **Homepage URL** — any URL works (e.g. the repo URL); it's not used by this server.
- **Webhook** — uncheck **Active**. This server doesn't receive webhooks, so there's nothing to
  configure or expose.
- **Repository permissions** — grant only what the tools you'll use actually need:

  | Permission            | Level | Needed for |
  | ---------------------- | ----- | ----------- |
  | Contents               | Read & write* | `gh_file_get`, `gh_search_code` (*write only if you'll add file-write tools later; today none exist) |
  | Metadata               | Read-only (mandatory, auto-selected) | every request |
  | Pull requests           | Read & write | `gh_pr_*`, `gh_review_*` |
  | Issues                  | Read & write | `gh_issue_*` |
  | Checks                  | Read-only | `gh_pr_checks` |
  | Actions                 | Read-only | `gh_run_*` |

  Skip permissions you don't need — e.g. drop Issues/PR write scopes for a read-only deployment.
- **Where can this GitHub App be installed?** — "Only on this account" unless you deliberately
  want it installable by other orgs/users.

Click **Create GitHub App**. On the page that follows, note the **App ID** near the top — that's
`GITHUB_APP_ID`.

### 2. Generate a private key

Still on the App's settings page, scroll to **Private keys** → **Generate a private key**. This
downloads a `<app-name>.<date>.private-key.pem` file — GitHub only lets you see it once, so save
it somewhere safe immediately (a secrets manager, not the repo).

### 3. Install the App

From the same settings page, click **Install App** in the left sidebar, choose the account/org,
and select either "All repositories" or specific repositories the agent should be able to touch.

After installing, grab the **Installation ID** — it's the number in the URL you land on:
```
https://github.com/settings/installations/<INSTALLATION_ID>
```
(or, for an org, `https://github.com/organizations/<org>/settings/installations/<INSTALLATION_ID>`).
That's `GITHUB_APP_INSTALLATION_ID`. If you already navigated away, go to
**https://github.com/settings/installations**, click **Configure** next to the App, and read the
number out of the URL you land on.

> **Don't confuse this with the App's Client ID.** The App's general settings page shows a
> **Client ID** that looks like `Iv23liXXXXXXXXXXXXXX` — that is *not* the Installation ID, and
> using it here fails with a 404 on the token-exchange call:
> `GET https://api.github.com/app/installations/<id>/access_tokens`. The real Installation ID is
> always a plain number (e.g. `78901234`); only the URL from **Install App** /
> **Settings → Installations** above gives you the right one.

If you install the App on multiple accounts/orgs, each installation gets its own ID — this server
only talks to one installation at a time, so run one server instance (with its own env vars) per
installation if you need more than one.

### 4. Set the environment variables

```bash
export GITHUB_APP_ID="123456"
export GITHUB_APP_INSTALLATION_ID="78901234"
export GITHUB_APP_PRIVATE_KEY="$(cat /path/to/my-agent-bot.2026-07-02.private-key.pem)"
```

`GITHUB_APP_PRIVATE_KEY` can be the PEM's real multi-line content (as above) or a single line with
literal `\n` escapes (common when a secrets manager flattens it) — `auth.py` normalizes either
form before signing the JWT. Either way, treat it like any other credential: pull it from a
secrets manager or `.env` file that's gitignored, never commit it, never hardcode it.

If you're wiring this up through
[`ansible-ai-agents`](https://github.com/jahrik/ansible-ai-agents): that role registers the
`github` (plus `ws` and `data`) servers and wires these credentials into the `github` server's
environment for you. Set `ai_agents_mcp_github_app_id`, `ai_agents_mcp_github_app_installation_id`,
and `ai_agents_mcp_github_app_private_key_file` (a path to the PEM on the target host); when all
three are present the role exports `GITHUB_APP_ID` / `GITHUB_APP_INSTALLATION_ID` /
`GITHUB_APP_PRIVATE_KEY` to the server. See that role's docs for supplying the PEM secret.

### 5. Verify it works

```bash
uv run mcp-github &   # or: mcp-github, if installed as a tool
```

Then, from an MCP client (or directly via `uv run python`), call a read tool such as
`gh_repo_get` for a repo the installation has access to. A successful response means the JWT →
installation-token exchange worked. To confirm bot attribution specifically, run a write tool
(with `MCP_GITHUB_ALLOW_WRITE=1` set) like `gh_issue_comment` against a scratch issue and check
that the comment shows up as `<app-name>[bot]`, not your own account.

### Rotating or revoking access

- **Rotate the key:** generate a new private key on the App's settings page (old keys can be
  deleted independently), update `GITHUB_APP_PRIVATE_KEY`, restart the server. No re-install
  needed.
- **Revoke access:** uninstall the App from the account/repo (Settings → Installations →
  Configure → Uninstall), or delete the App entirely to kill every installation at once.
- Installation Access Tokens are short-lived (≤1h) and cached in-memory for ~50 minutes — there's
  no long-lived token sitting on disk to rotate.

## Read tools

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
- `gh_api_graphql`

The review-read tools take `bot_only` to keep just the Copilot/bot comments — the actionable ones in a review.

## Write tools

Writes are disabled unless `MCP_GITHUB_ALLOW_WRITE=1` is set.

- `gh_pr_create` — when `base` is omitted it defaults to the repo's default branch (rather than 422ing); a genuine 422 surfaces the API's `errors` array.
- `gh_pr_edit`
- `gh_pr_comment`
- `gh_pr_merge`
- `gh_pr_request_reviewers` — to request a Copilot review, pass the login `Copilot` (not the `copilot-pull-request-reviewer[bot]` app slug). GitHub silently ignores an unrecognized reviewer login, so the tool adds a `warning` naming anyone it dropped.
- `gh_run_rerun` — rerun a GitHub Actions workflow run, or only its failed jobs (`failed_only`).
- `gh_issue_create`
- `gh_issue_comment`
- `gh_issue_edit` — change state (close/reopen via `state` + `state_reason`), title, body, or labels.
- `gh_review_comment_reply`
- `gh_review_thread_resolve`

Every write invocation is recorded in a local SQLite audit log at `~/.mcp/audit.db`.

## Behavior

- **Input validation** — inputs (repository slugs, refs, issue numbers) are validated with Pydantic before any API call; malformed inputs are rejected.
- **Audit logging** — the audit log records each write's command, execution duration, success status, and full stderr.
- **Error handling** — on failure the server returns context rather than a raw Python stack trace.

## Configuration

- `MCP_GITHUB_ALLOW_WRITE`: Set to `1` to enable the write tools. Unset, all write tools are refused; read tools always work.
- `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `GITHUB_APP_PRIVATE_KEY`: GitHub App credentials — see [Setup](#setup-create-and-install-the-github-app).
