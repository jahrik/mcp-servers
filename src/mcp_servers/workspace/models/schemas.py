from __future__ import annotations

from pydantic import BaseModel, Field

_ROOT_DESC = "Workspace root to scan. Defaults to $MCP_WORKSPACE_ROOT, then ~/github."


class WsStatusArgs(BaseModel, frozen=True):
    root: str | None = Field(None, description=_ROOT_DESC)
    attention_only: bool = Field(
        False,
        description=(
            "Only return repos needing attention: dirty tree, ahead/behind upstream, "
            "stashes, or no upstream."
        ),
    )


class WsRepoArgs(BaseModel, frozen=True):
    path: str = Field(
        description="Repo path — absolute, ``~``-relative, or relative to the workspace root."
    )
    root: str | None = Field(None, description=_ROOT_DESC)


class WsBranchesArgs(BaseModel, frozen=True):
    root: str | None = Field(None, description=_ROOT_DESC)
