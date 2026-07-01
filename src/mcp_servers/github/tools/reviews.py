from __future__ import annotations

from mcp_servers._common import run_gh, validate_repo

from ..models.schemas import (
    ReviewCommentReplyArgs,
    ReviewCommentsListArgs,
    ReviewThreadResolveArgs,
    ReviewThreadsGetArgs,
)
from ..utils import _audit_log

_REVIEW_COMMENT_PROJECT = "{id, author: .user.login, path, line: (.line // .original_line), body}"
_BOT_SELECT_REST = (
    'select(.user.type == "Bot" or (.user.login | ascii_downcase | contains("copilot")))'
)
_BOT_THREAD_JQ = (
    ".data.repository.pullRequest.reviewThreads.nodes |= "
    "map(select(any(.comments.nodes[]; "
    '.author.__typename == "Bot" or (.author.login | ascii_downcase | contains("copilot")))))'
)


def _review_comment_jq(*, bot_only: bool) -> str:
    """`gh api --jq` program that projects (and optionally bot-filters) comments."""
    stages = [".[]"]
    if bot_only:
        stages.append(_BOT_SELECT_REST)
    stages.append(_REVIEW_COMMENT_PROJECT)
    return " | ".join(stages)


_THREADS_QUERY = """
query($owner:String!,$name:String!,$pr:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$pr){
      reviewThreads(first:100){
        nodes{
          id
          isResolved
          isOutdated
          comments(first:100){
            nodes{ databaseId author{login __typename} path line body }
          }
        }
      }
    }
  }
}
"""

_RESOLVE_MUTATION = """
mutation($threadId:ID!){
  resolveReviewThread(input:{threadId:$threadId}){ thread{ id isResolved } }
}
"""


def gh_review_comments_list(args: ReviewCommentsListArgs) -> str:
    """List a PR's inline review comments (read-only).

    Returns one JSON object per comment with the ``id`` (needed to reply),
    author, ``path``, ``line``, and body.

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        bot_only: Keep only bot/Copilot comments — the actionable ones in an
            automated review.
    """
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    validate_repo(repo)
    return run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{int(pr)}/comments",
            "--paginate",
            "--jq",
            _review_comment_jq(bot_only=bot_only),
        ]
    )


def gh_review_threads_get(args: ReviewThreadsGetArgs) -> str:
    """List a PR's review threads with ids and resolved state (read-only).

    Each thread carries its node ``id`` (pass to ``gh_review_thread_resolve``), its
    ``isResolved``/``isOutdated`` state, and the comments in it (each with a
    ``databaseId`` matching a ``gh_review_comments_list`` id).

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        bot_only: Keep only threads that contain a bot/Copilot comment.
    """
    repo = args.repo
    pr = args.pr
    bot_only = args.bot_only
    validate_repo(repo)
    owner, _, name = repo.partition("/")
    cmd_args = [
        "api",
        "graphql",
        "-f",
        f"owner={owner}",
        "-f",
        f"name={name}",
        "-F",
        f"pr={int(pr)}",
        "-f",
        f"query={_THREADS_QUERY}",
    ]
    if bot_only:
        # Filter thread nodes in place, preserving the response envelope.
        cmd_args += ["--jq", _BOT_THREAD_JQ]
    return run_gh(cmd_args)


@_audit_log
def gh_review_comment_reply(args: ReviewCommentReplyArgs) -> str:
    """Reply to a PR inline review comment's thread (write).

    Args:
        repo: Repository as ``owner/name``.
        pr: Pull request number.
        comment_id: The review comment id to reply to (from
            ``gh_review_comments_list``).
        body: Reply text.
    """
    repo = args.repo
    pr = args.pr
    comment_id = args.comment_id
    body = args.body
    validate_repo(repo)
    return run_gh(
        [
            "api",
            "-X",
            "POST",
            f"repos/{repo}/pulls/{int(pr)}/comments/{int(comment_id)}/replies",
            "-f",
            f"body={body}",
        ]
    )


@_audit_log
def gh_review_thread_resolve(args: ReviewThreadResolveArgs) -> str:
    """Resolve a PR review thread by its node id (write).

    Args:
        thread_id: The review thread node id from ``gh_review_threads_get``.
    """
    thread_id = args.thread_id
    return run_gh(
        [
            "api",
            "graphql",
            "-f",
            f"threadId={thread_id}",
            "-f",
            f"query={_RESOLVE_MUTATION}",
        ]
    )
