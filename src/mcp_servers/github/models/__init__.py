from pydantic import BaseModel, Field

_REPO_PATTERN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$"


class RepoListArgs(BaseModel, frozen=True):
    owner: str = Field(
        pattern=r"^[a-zA-Z0-9-]+$", description="The GitHub user or organization name."
    )
    limit: int = Field(
        30, ge=1, le=100, description="Maximum number of repositories to return (1-100)."
    )


class RepoArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")


class PrListArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    state: str = Field("open", description="``open``, ``closed``, ``merged``, or ``all``.")
    limit: int = Field(20, ge=1, le=100, description="Maximum number of PRs to return (1-100).")


class PrArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    number: int = Field(description="Pull request number.")


class PrCreateArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    title: str = Field(description="Title of the pull request.")
    body: str = Field(description="Body/description of the pull request.")
    head: str = Field(description="The branch that contains the commits for your pull request.")
    base: str | None = Field(None, description="The branch into which you want your code merged.")
    draft: bool = Field(False, description="Mark the pull request as a draft.")


class PrCommentArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    pr: int = Field(description="Pull request number.")
    body: str = Field(description="The comment body.")


class PrMergeArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    pr: int = Field(description="Pull request number.")
    merge_method: str = Field(
        "squash", description="``squash``, ``merge``, or ``rebase``. Default is ``squash``."
    )
    delete_branch: bool = Field(
        False, description="Delete the local and remote branch after merge."
    )


class IssueListArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    state: str = Field("open", description="``open``, ``closed``, or ``all``.")
    limit: int = Field(20, ge=1, le=100, description="Maximum number of issues to return (1-100).")


class IssueArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    number: int = Field(description="Issue number.")


class IssueCreateArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    title: str = Field(description="Title of the issue.")
    body: str = Field(description="Body/description of the issue.")


class IssueCommentArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    issue: int = Field(description="Issue number.")
    body: str = Field(description="The comment body.")


class FileGetArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    path: str = Field(description="Path to the file within the repo.")
    ref: str = Field("HEAD", description="Branch, tag, or commit SHA (default ``HEAD``).")


class SearchCodeArgs(BaseModel, frozen=True):
    query: str = Field(description="Search expression (GitHub code-search syntax).")
    repo: str | None = Field(
        None,
        pattern=_REPO_PATTERN,
        description="Optional ``owner/name`` to scope the search to one repo.",
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum number of results (1-100).")


class SearchPrsArgs(BaseModel, frozen=True):
    query: str = Field(description="Search expression (GitHub search syntax).")
    repo: str | None = Field(
        None,
        pattern=_REPO_PATTERN,
        description="Optional ``owner/name`` to scope the search to one repo.",
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum number of results (1-100).")


class SearchIssuesArgs(BaseModel, frozen=True):
    query: str = Field(description="Search expression (GitHub search syntax).")
    repo: str | None = Field(
        None,
        pattern=_REPO_PATTERN,
        description="Optional ``owner/name`` to scope the search to one repo.",
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum number of results (1-100).")


class RunListArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    branch: str | None = Field(None, description="Optional branch name to filter by.")
    workflow: str | None = Field(
        None, description="Optional workflow name or filename to filter by."
    )
    limit: int = Field(20, ge=1, le=100, description="Maximum number of runs to return (1-100).")


class RunArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    run_id: int = Field(description="The run ID (databaseId).")


class ReviewCommentsListArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    pr: int = Field(description="Pull request number.")
    bot_only: bool = Field(False, description="Keep only bot/Copilot comments.")


class ReviewThreadsGetArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    pr: int = Field(description="Pull request number.")
    bot_only: bool = Field(
        False, description="Keep only threads that contain a bot/Copilot comment."
    )


class ReviewCommentReplyArgs(BaseModel, frozen=True):
    repo: str = Field(pattern=_REPO_PATTERN, description="Repository as ``owner/name``.")
    pr: int = Field(description="Pull request number.")
    comment_id: int = Field(description="The review comment id to reply to.")
    body: str = Field(description="Reply text.")


class ReviewThreadResolveArgs(BaseModel, frozen=True):
    thread_id: str = Field(description="The review thread node id from ``gh_review_threads_get``.")


class ApiGetArgs(BaseModel, frozen=True):
    endpoint: str = Field(description="The API endpoint path (e.g. ``repos/owner/repo/pulls``).")
    jq_filter: str | None = Field(
        None, description="Optional jq filter string to parse the response."
    )


class GraphqlQueryArgs(BaseModel, frozen=True):
    query: str = Field(description="The GraphQL query string.")
    jq_filter: str | None = Field(
        None, description="Optional jq filter string to parse the response."
    )
